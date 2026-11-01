"""Exercise deletion/restore on an isolated real Chroma collection, no APIs."""
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from app.rag.vector_store import client
from scripts.quarantine_test_chunks import IDS, quarantine, read_backup, restore


class QuarantineTestChunks(unittest.TestCase):
    def setUp(self):
        self.collection = client.create_collection('quarantine-' + uuid4().hex, embedding_function=None)
        self.addCleanup(client.delete_collection, self.collection.name)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.backup = Path(folder.name) / 'records.json'
        self.audit = {'ids': list(IDS), 'documents': ['test one', 'test two', 'test three'],
                      'metadatas': [{'source_file': 'UAV07.pdf', 'page_number': '12'} for _ in IDS]}
        self.vectors = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]
        self.collection.add(**self.audit, embeddings=self.vectors)
        self.collection.add(ids=['real-record'], documents=['real data'], embeddings=[[.25, .5, .75]],
                            metadatas=[{'source_file': 'real.pdf'}])

    def test_quarantine_and_restore_preserve_vectors_and_other_records(self):
        untouched = self.collection.get(ids=['real-record'], include=['documents', 'metadatas'])
        result = quarantine(self.collection, self.audit, self.backup)
        self.assertEqual((result['before'], result['after']), (4, 1))
        self.assertEqual(read_backup(self.backup)['records']['embeddings'], self.vectors)
        self.assertEqual(restore(self.collection, self.backup), 3)
        self.assertEqual(self.collection.count(), 4)
        self.assertEqual(self.collection.get(ids=['real-record'], include=['documents', 'metadatas']), untouched)
        restored = self.collection.get(ids=list(IDS), include=['documents', 'metadatas', 'embeddings'])
        for i, record_id in enumerate(restored['ids']):
            j = self.audit['ids'].index(record_id)
            self.assertEqual(restored['documents'][i], self.audit['documents'][j])
            self.assertEqual(restored['metadatas'][i], self.audit['metadatas'][j])
            self.assertEqual(restored['embeddings'][i].tolist(), self.vectors[j])
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            restore(self.collection, self.backup)

    def test_changed_record_cannot_be_deleted_using_old_audit(self):
        self.collection.update(ids=[IDS[0]], documents=['owner changed this'], embeddings=[[1., 0., 0.]])
        with self.assertRaisesRegex(ValueError, 'changed since audit'):
            quarantine(self.collection, self.audit, self.backup)
        self.assertEqual(self.collection.count(), 4)
        self.assertFalse(self.backup.exists())

    def test_existing_backup_is_never_overwritten(self):
        self.backup.write_bytes(b'existing recovery data')
        with self.assertRaises(FileExistsError):
            quarantine(self.collection, self.audit, self.backup)
        self.assertEqual(self.collection.count(), 4)
        self.assertEqual(self.backup.read_bytes(), b'existing recovery data')

    def test_corrupt_backup_cannot_be_restored(self):
        quarantine(self.collection, self.audit, self.backup)
        envelope = json.loads(self.backup.read_text(encoding='utf-8'))
        envelope['payload']['records']['documents'][0] = 'changed'
        self.backup.write_text(json.dumps(envelope), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            restore(self.collection, self.backup)
        self.assertEqual(self.collection.count(), 1)
