#!/usr/bin/env python3
"""Summarize WASM structure without emitting decompiled implementation or data.

Usage: python probe_wasm.py path/to/module.wasm --output wasm-structure.json
Standard library only. This parses the standard sections needed for this probe;
it is not a general WebAssembly validator. Analysis never executes the module.
"""
import argparse
import hashlib
import json
from pathlib import Path


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def byte(self):
        value = self.data[self.pos]
        self.pos += 1
        return value

    def uleb(self):
        value = shift = 0
        while True:
            b = self.byte()
            value |= (b & 127) << shift
            if not b & 128:
                return value
            shift += 7
            if shift > 70:
                raise ValueError('invalid LEB128')

    def name(self):
        size = self.uleb()
        value = self.data[self.pos:self.pos + size].decode('utf-8')
        self.pos += size
        return value

    def limits(self):
        flags = self.uleb()
        result = {'minimum_pages_or_elements': self.uleb(),
                  'shared': bool(flags & 2), 'memory64': bool(flags & 4)}
        if flags & 1:
            result['maximum_pages_or_elements'] = self.uleb()
        return result


def probe(data):
    if data[:8] != b'\x00asm\x01\x00\x00\x00':
        raise ValueError('expected WebAssembly binary version 1')
    names = ['Custom', 'Type', 'Import', 'Function', 'Table', 'Memory',
             'Global', 'Export', 'Start', 'Element', 'Code', 'Data', 'DataCount']
    kinds = ['function', 'table', 'memory', 'global', 'tag']
    result = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
              'sections': [], 'imports': [], 'exports': []}
    reader = Reader(data)
    reader.pos = 8
    while reader.pos < len(data):
        section_id = reader.byte()
        size = reader.uleb()
        offset = reader.pos
        section = Reader(data[offset:offset + size])
        reader.pos += size
        entry = {'id': section_id, 'name': names[section_id],
                 'offset': offset, 'size': size}
        result['sections'].append(entry)
        if section_id == 0:
            entry['custom_name'] = section.name()
        elif section_id == 8:
            entry['start_function'] = section.uleb()
        else:
            entry['count'] = section.uleb()
        if section_id == 2:
            for _ in range(entry['count']):
                item = {'module': section.name(), 'name': section.name()}
                kind = section.byte()
                item['kind'] = kinds[kind]
                if kind == 0:
                    item['signature_index'] = section.uleb()
                elif kind == 1:
                    item['reference_type'] = section.byte()
                    item.update(section.limits())
                elif kind == 2:
                    item.update(section.limits())
                elif kind == 3:
                    item.update(value_type=section.byte(), mutable=bool(section.byte()))
                else:
                    raise ValueError('unsupported import kind')
                result['imports'].append(item)
        if section_id == 7:
            for _ in range(entry['count']):
                result['exports'].append({'name': section.name(),
                    'kind': kinds[section.byte()], 'index': section.uleb()})
    result['has_custom_sections'] = any(x['id'] == 0 for x in result['sections'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = json.dumps(probe(args.binary.read_bytes()), indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
