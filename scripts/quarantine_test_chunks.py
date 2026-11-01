"""Reversibly quarantine the three audited uav07-test-* records, offline.

No embedding generation, collection reset or source-wide deletion. The audit
must match the current documents and metadata. An exclusive, fsynced backup
includes vectors and a checksum before any delete. Restore refuses overwrites.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

IDS = ('uav07-test-1', 'uav07-test-2', 'uav07-test-3')


def _encoded(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def _records(collection) -> dict:
    data = collection.get(ids=list(IDS), include=['documents', 'metadatas', 'embeddings'])
    order = sorted(range(len(data['ids'])), key=lambda i: data['ids'][i])
    return {key: [data[key][i].tolist() if key == 'embeddings' else data[key][i] for i in order]
            for key in ('ids', 'documents', 'metadatas', 'embeddings')}


def _validate(payload: dict) -> dict:
    data = payload['records']
    if payload.get('version') != 1 or tuple(data['ids']) != IDS:
        raise ValueError('Backup must contain exactly the three audited test IDs')
    if any(len(data[key]) != len(IDS) for key in ('documents', 'metadatas', 'embeddings')):
        raise ValueError('Incomplete backup')
    if any(meta.get('source_file') != 'UAV07.pdf' for meta in data['metadatas']):
        raise ValueError('Unexpected source file')
    if any(not vector for vector in data['embeddings']):
        raise ValueError('Missing vectors; cannot restore without an embedding call')
    return data


def read_backup(path: Path) -> dict:
    envelope = json.loads(path.read_text(encoding='utf-8'))
    payload = envelope['payload']
    if hashlib.sha256(_encoded(payload)).hexdigest() != envelope['sha256']:
        raise ValueError('Backup checksum mismatch')
    _validate(payload)
    return payload


def quarantine(collection, audit: dict, output: Path) -> dict:
    records = _records(collection)
    payload = {'version': 1, 'collection': collection.name, 'records': records}
    _validate(payload)
    if set(audit['ids']) != set(IDS):
        raise ValueError('Audit does not match the known test IDs')
    for i, record_id in enumerate(records['ids']):
        index = audit['ids'].index(record_id)
        if any(records[key][i] != audit[key][index] for key in ('documents', 'metadatas')):
            raise ValueError('Record changed since audit; no deletion performed')
    all_ids = set(collection.get(include=[])['ids'])
    output.parent.mkdir(parents=True, exist_ok=True)
    envelope = {'payload': payload, 'sha256': hashlib.sha256(_encoded(payload)).hexdigest()}
    # Exclusive creation protects any existing recovery copy, even on a retry.
    with output.open('xb') as stream:
        stream.write(_encoded(envelope))
        stream.flush()
        os.fsync(stream.fileno())
    saved = read_backup(output)
    if saved != payload or _records(collection) != records:
        raise ValueError('Source changed while backing up; no deletion performed')
    collection.delete(ids=list(IDS))
    remaining = set(collection.get(include=[])['ids'])
    if remaining != all_ids - set(IDS):
        raise RuntimeError('Collection changed during quarantine; inspect backup and concurrent ingestion')
    return {'before': len(all_ids), 'after': len(remaining), 'quarantined': list(IDS),
            'backup': str(output), 'sha256': envelope['sha256']}


def restore(collection, backup: Path) -> int:
    payload = read_backup(backup)
    if payload['collection'] != collection.name:
        raise ValueError('Backup belongs to another collection')
    if collection.get(ids=list(IDS), include=[])['ids']:
        raise ValueError('Restore refuses to overwrite existing records')
    records = payload['records']
    collection.add(**records)
    if _records(collection) != records:
        raise RuntimeError('Restored records differ from backup')
    return len(IDS)


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('quarantine', 'restore'))
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--audit', type=Path)
    args = parser.parse_args()
    # No provider calls, telemetry or downloading an embedding function.
    import socket
    from unittest.mock import patch
    with patch.object(socket.socket, 'connect', side_effect=RuntimeError('Maintenance is offline')):
        import chromadb
        from chromadb.config import Settings
        collection = chromadb.PersistentClient(path=os.getenv('CHROMA_PATH', 'chroma_db'),
            settings=Settings(anonymized_telemetry=False)).get_collection('drone_knowledge', embedding_function=None)
        if args.command == 'quarantine':
            if not args.audit:
                parser.error('--audit is required for quarantine')
            result = quarantine(collection, json.loads(args.audit.read_text(encoding='utf-8')), args.backup)
        else:
            result = {'restored': restore(collection, args.backup)}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
