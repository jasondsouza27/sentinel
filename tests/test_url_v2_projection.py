import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from url_v2_fixtures import test_config,write_parquet_fixture,LocalRangeSession

@unittest.skipUnless(importlib.util.find_spec("pyarrow"),"requires isolated URL data runtime")
class ProjectionTests(unittest.TestCase):
    def setUp(self):
        from sentinel.url_v2.contracts import SourceCatalog,SourceFile,PHRESH_REVISION
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name); self.values={}; files=[]; paths={}
        for part in ("train","test"):
            name=f"data/{part}-00000-of-00001.parquet"; path=self.root/(part+".parquet"); self.values[part]=write_parquet_fixture(path)
            files.append(SourceFile("phreshphish",PHRESH_REVISION,name,part,path.stat().st_size,"a"*64,None)); paths[name]=path
        self.catalog=SourceCatalog((),tuple(files),{"schema":"url-source-catalog-v2","source_files":[f.__dict__ for f in files]})
        self.session=LocalRangeSession(paths); self.config=test_config()
    def test_real_arrow_projection_excludes_html_and_round_trips_nulls(self):
        from sentinel.url_v2.projection import project_phresh,iter_phresh_observations
        import pyarrow.parquet as pq
        output=self.root/"out"; manifest=project_phresh(self.catalog,self.session,output,self.config)
        self.assertEqual(manifest["projected_columns"],["url","label","date","sha256"])
        self.assertIs(manifest["full_file_checksum_verified"],False); self.assertEqual(manifest["status"],"complete")
        self.assertLessEqual(max(manifest["batch_lengths"]),4096)
        rows=list(iter_phresh_observations(output,self.catalog)); self.assertEqual(len(rows),6)
        self.assertEqual([r.original_url for r in rows[:3]],self.values["train"]["url"])
        self.assertEqual([r.opaque_id for r in rows[:3]],["opaque-a","opaque-b",None])
        for file in self.catalog.files:
            md=pq.read_metadata(self.session.paths[file.path])
            for i in range(md.num_row_groups):
                for j in range(md.num_columns):
                    c=md.row_group(i).column(j)
                    if c.path_in_schema not in ("html","langs"): continue
                    lo=min(x for x in (c.dictionary_page_offset,c.data_page_offset) if x is not None and x>=0); hi=lo+c.total_compressed_size
                    for name,start,length in self.session.requests:
                        if name==file.path: self.assertFalse(start<hi and lo<start+length,(c.path_in_schema,start,length))
        first=(output/"observations.jsonl").read_bytes()
        again=self.root/"again"; project_phresh(self.catalog,self.session,again,self.config)
        self.assertEqual(first,(again/"observations.jsonl").read_bytes())
        (output/"observations.jsonl").write_bytes(b"changed")
        with self.assertRaises(DatasetError): list(iter_phresh_observations(output,self.catalog))
    def test_magic_footer_schema_external_and_limits_rejected_without_manifest(self):
        from sentinel.url_v2.projection import project_phresh
        from dataclasses import replace
        import pyarrow.parquet as pq
        for kind in ("magic","encryption","footer","nested","missing","external","limit"):
            with self.subTest(kind=kind):
                file=self.catalog.files[0]; path=self.root/(kind+".parquet"); write_parquet_fixture(path,nested=kind=="nested",missing=kind=="missing")
                data=bytearray(path.read_bytes())
                if kind=="magic": data[:4]=b"WRNG"
                if kind=="encryption": data[-4:]=b"PARE"
                if kind=="footer": data[-8:-4]=(2097153).to_bytes(4,"little")
                if kind in ("magic","encryption","footer"): path.write_bytes(data)
                if kind=="external": md=pq.read_metadata(path); md.set_file_path("external.parquet"); md.write_metadata_file(path)
                file=replace(file,size=path.stat().st_size); catalog=type(self.catalog)((),(file,),self.catalog.manifest); session=LocalRangeSession({file.path:path}); config=test_config()
                if kind=="limit": config["projection"]["max_range_bytes"]=1
                out=self.root/(kind+"-out")
                with self.assertRaises(DatasetError): project_phresh(catalog,session,out,config)
                self.assertFalse(out.exists())
    def test_unaudited_read_refused_and_chunk_offsets_checked(self):
        from sentinel.url_v2.projection import plan_projection,PermittedView,validate_chunks
        file=self.catalog.files[0]; plan=plan_projection(file,self.session,self.config)
        view=PermittedView(file,self.session,plan["allowed_spans"])
        import pyarrow.parquet as pq
        fixture=pq.read_metadata(self.session.paths[file.path])
        view.seek(fixture.row_group(0).column(4).data_page_offset)
        with self.assertRaises(DatasetError): view.read(1)
        for chunks in [
          [{"name":"url","start":-1,"length":1,"file_path":""}],
          [{"name":"url","start":4,"length":10,"file_path":""},{"name":"html","start":8,"length":10,"file_path":""}],
          [{"name":"url","start":4,"length":999999,"file_path":""}],
        ]:
            with self.assertRaises(DatasetError): validate_chunks(chunks,100,80,self.config)
    def test_pilot_and_interruption_do_not_claim_complete_corpus(self):
        from sentinel.url_v2.projection import project_phresh
        manifest=project_phresh(self.catalog,self.session,self.root/"pilot",self.config,pilot=True)
        self.assertEqual(manifest["status"],"transport-schema-pilot"); self.assertEqual(manifest["purpose"],"pilot")
        class Interrupted(LocalRangeSession):
            def read_range(self,file,start,length):
                if len(self.requests)>=5: raise DatasetError("interrupted")
                return super().read_range(file,start,length)
        with self.assertRaises(DatasetError): project_phresh(self.catalog,Interrupted(self.session.paths),self.root/"partial",self.config)
        self.assertFalse((self.root/"partial").exists())

if __name__=="__main__": unittest.main()
