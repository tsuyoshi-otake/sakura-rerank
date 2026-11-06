"""Documentation qualification rejects unsafe archives and leaves corpus bytes undecoded."""
import bz2
import importlib.util
import io
from pathlib import Path
import tarfile
import unittest

PATH = Path(__file__).resolve().parents[1]/'research/issue-35-knbc-qualification/qualify_knbc.py'
SPEC = importlib.util.spec_from_file_location('knbc_documentation_contract', PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def archive(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as target:
        for name, body, kind in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.size = len(body) if kind == tarfile.REGTYPE else 0
            if kind in (tarfile.LNKTYPE, tarfile.SYMTYPE):
                info.linkname = 'outside'
            target.addfile(info, io.BytesIO(body) if kind == tarfile.REGTYPE else None)
    return bz2.compress(stream.getvalue())


class KnBCDocumentationTests(unittest.TestCase):
    def test_only_documentation_read_and_corpus_invalid_utf8_left_opaque(self):
        raw = archive([('root/README', b'fixture terms', tarfile.REGTYPE),
                       ('root/corpus/item', b'\xff\xfe', tarfile.REGTYPE)])
        inventory, docs, _ = MODULE.inspect_archive(raw)
        self.assertEqual(len(inventory), 2)
        self.assertEqual([d['raw'] for d in docs], [b'fixture terms'])

    def test_unsafe_paths(self):
        for name in ('/outside', '../outside', 'root/../x', 'C:/x', 'root\\x', 'root/x\n'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                MODULE.inspect_archive(archive([(name, b'x', tarfile.REGTYPE)]))

    def test_links_and_special_members(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                MODULE.inspect_archive(archive([('root/member', b'', kind)]))

    def test_case_and_dot_aliases_rejected(self):
        for names in (('root/A','root/a'), ('./root/a','root/a')):
            with self.subTest(names=names), self.assertRaises(ValueError):
                MODULE.inspect_archive(archive([(n,b'x',tarfile.REGTYPE) for n in names]))

    def test_expansion_bound(self):
        with self.assertRaisesRegex(ValueError, 'expanded_bound'):
            MODULE.inspect_archive(archive([('root/a', b'x'*10000, tarfile.REGTYPE)]), {'expanded_bytes':100})

    def test_compressed_stream_must_end_exactly(self):
        raw = archive([('root/a', b'x', tarfile.REGTYPE)])
        for value in (raw[:-5], raw+b'junk', raw+raw):
            with self.subTest(length=len(value)), self.assertRaises((ValueError, EOFError)):
                MODULE.inspect_archive(value)

    def test_compressed_and_member_count_bounds(self):
        raw = archive([('root/a', b'x', tarfile.REGTYPE), ('root/b', b'y', tarfile.REGTYPE)])
        for limits in ({'compressed_bytes':1}, {'members':1}, {'member_bytes':0}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                MODULE.inspect_archive(raw, limits)

    def test_document_bounds(self):
        raw = archive([('root/README', b'abc', tarfile.REGTYPE), ('root/LICENSE', b'xyz', tarfile.REGTYPE)])
        for limits in ({'documents':1}, {'document_bytes':2}, {'document_total_bytes':5}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                MODULE.inspect_archive(raw, limits)

    def test_document_depth_and_exact_name(self):
        raw = archive([(n,b'\xff',tarfile.REGTYPE) for n in ('a/b/c/README','root/README-other','root/data.txt')])
        self.assertEqual(MODULE.inspect_archive(raw)[1], [])

    def test_empty_archive_rejected(self):
        with self.assertRaisesRegex(ValueError, 'empty_archive'):
            MODULE.inspect_archive(archive([]))

    def test_explicit_metadata_only_symlink_policy_does_not_follow_link(self):
        raw = archive([('root/link', b'', tarfile.SYMTYPE), ('root/README', b'fixture terms', tarfile.REGTYPE)])
        inventory, documents, _ = MODULE.inspect_archive(raw, permit_unfollowed_symlinks=True)
        self.assertEqual(inventory[0]['kind'], 'unfollowed_symlink')
        self.assertEqual([d['raw'] for d in documents], [b'fixture terms'])

    def test_document_named_symlink_is_never_read(self):
        raw = archive([('root/README', b'', tarfile.SYMTYPE)])
        self.assertEqual(MODULE.inspect_archive(raw, permit_unfollowed_symlinks=True)[1], [])

    def test_metadata_only_policy_still_rejects_hard_links(self):
        with self.assertRaisesRegex(ValueError, 'member_type'):
            MODULE.inspect_archive(archive([('root/link', b'', tarfile.LNKTYPE)]), permit_unfollowed_symlinks=True)


if __name__ == '__main__':
    unittest.main()
