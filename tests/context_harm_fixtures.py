"""Invented CAD-shaped records; never a source of research performance."""
import csv
import io
import zipfile

FIELDS = (
    'id', 'info_id', 'info_subreddit', 'info_subreddit_id', 'info_id.parent',
    'info_id.link', 'info_thread.id', 'info_order', 'info_image.saved',
    'annotation_Primary', 'annotation_Secondary', 'annotation_Context',
    'annotation_Target', 'annotation_Target_top.level.category',
    'annotation_highlighted', 'meta_author', 'meta_created_utc', 'meta_date',
    'meta_day', 'meta_permalink', 'split', 'subreddit_seen', 'meta_text',
)


def cad_row(case_id='target', *, thread='thread', author='writer', parent='NA',
            root='root', order='1', text='A plain invented statement.',
            label='Neutral', split='train', context='NA'):
    row = dict.fromkeys(FIELDS, 'NA')
    row.update({'id': case_id + '-' + label, 'info_id': case_id,
                'info_subreddit': 'invented_community', 'info_subreddit_id': 'fake',
                'info_id.parent': parent, 'info_id.link': root,
                'info_thread.id': thread, 'info_order': order,
                'info_image.saved': 'False', 'annotation_Primary': label,
                'annotation_Context': context, 'meta_author': author,
                'meta_created_utc': '1546300800', 'meta_date': '2019-01-01',
                'meta_day': 'Tuesday', 'split': split, 'subreddit_seen': 'True',
                'meta_text': text})
    return row


def tsv_bytes(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter='\t',
                            quoting=csv.QUOTE_NONE, quotechar=None,
                            lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def archive_bytes(rows, *, extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('data/cad_v1_1.tsv', tsv_bytes(rows))
        archive.writestr('data/cad_codebook_april2021.pdf', b'%PDF-invented-fixture')
        for name, body in (extra or {}).items():
            archive.writestr(name, body)
    return stream.getvalue()
