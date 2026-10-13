import importlib
import unittest


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        try: self.Signer=importlib.import_module('sentinel.assessment_receipts').SnapshotSigner
        except ModuleNotFoundError: self.fail('exact snapshot receipts are not implemented')
        self.now=1000.0
        self.signer=self.Signer(b'a'*32,clock=lambda:self.now)
        self.submitted={'message':'Quoted "text"','conversation_turns':[]}
        self.result={'harm_assessment':{'state':'unavailable','model_version':None}}

    def test_signature_binds_exact_input_result_and_canonical_key_order(self):
        token=self.signer.issue(self.submitted,self.result)
        self.signer.verify(token,dict(reversed(list(self.submitted.items()))),self.result)
        with self.assertRaises(ValueError): self.signer.verify(token,{'message':'Edited'},self.result)
        with self.assertRaises(ValueError): self.signer.verify(token,self.submitted,{'harm_assessment':{'state':'complete'}})

    def test_expired_future_restart_and_malformed_tokens_need_recheck(self):
        token=self.signer.issue(self.submitted,self.result)
        self.now=1901
        with self.assertRaisesRegex(ValueError,'Recheck'): self.signer.verify(token,self.submitted,self.result)
        self.now=999
        with self.assertRaises(ValueError): self.signer.verify(token,self.submitted,self.result)
        self.now=1000
        other=self.Signer(b'b'*32,clock=lambda:self.now)
        with self.assertRaises(ValueError): other.verify(token,self.submitted,self.result)
        for value in ('',None,'x.y','x'*4096):
            with self.subTest(value=str(value)[:5]),self.assertRaises(ValueError): self.signer.verify(value,self.submitted,self.result)

    def test_nonfinite_json_is_never_signed(self):
        with self.assertRaises(ValueError): self.signer.issue({'value':float('nan')},self.result)


if __name__=='__main__': unittest.main()
