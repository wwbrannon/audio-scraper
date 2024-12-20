'''
An AudioChunk class encapsulating a chunk ingested from an online stream.
'''

from typing import Optional

import io
import os
import gzip
import json
import hashlib
import logging

from urllib.parse import urlparse
from functools import cached_property

import boto3


logger = logging.getLogger(__name__)


class AudioChunk:
    '''
    Encapsulates an audio file for processing
    '''

    def __init__(self, url: str, source: str,
                 lang: Optional[str] = None,
                 cache_dir: Optional[str] = None):
        super().__init__()

        self.url = url
        self.source = source
        self.lang = lang

        if self._storage_mode == 's3':
            self._client = boto3.client('s3')
            self.cache_dir = cache_dir
        else:
            self._client = None
            self.cache_dir = None

            if cache_dir is not None:
                logger.warning('Ignoring cache_dir with local files')

    def remove(self):
        '''
        Remove this chunk from the backing store (s3 or local files).
        '''

        if self._storage_mode == 's3':
            if self._is_cached:
                try:
                    os.unlink(self._cache_path)
                except FileNotFoundError:
                    pass

            bucket = self._url_parsed.netloc

            key = self._url_parsed.path
            if key.startswith('/'):
                key = key[1:]

            self._client.delete_object(Bucket=bucket, Key=key)
        else:  # self._storage_mode == 'file'
            try:
                os.unlink(self._url_parsed.path)
            except FileNotFoundError:
                pass

    @cached_property
    def _url_parsed(self):
        return urlparse(self.url)

    @cached_property
    def _storage_mode(self):
        mode = self._url_parsed.scheme.lower()

        if mode not in ('s3', 'file'):
            raise ValueError('Bad storage URL format')

        if mode == 'file' and self._url_parsed.netloc != '':
            raise ValueError('Bad file URL - has netloc')

        return mode

    def _read_data_s3(self):
        bucket = self._url_parsed.netloc

        key = self._url_parsed.path
        if key.startswith('/'):
            key = key[1:]

        resp = self._client.get_object(Bucket=bucket, Key=key)

        return resp['Body'].read()

    def _read_data_local(self):
        with open(self._url_parsed.path, 'rb') as fobj:
            return fobj.read()

    def _read_data(self):
        if self._storage_mode == 's3':
            return self._read_data_s3()

        return self._read_data_local()

    @property
    def _cache_path(self):
        assert self._storage_mode == 's3'

        bucket = self._url_parsed.netloc

        key = self._url_parsed.path
        if key.startswith('/'):
            key = key[1:]

        val = (bucket, key)
        fname = hashlib.sha1(str(val).encode('utf-8')).hexdigest()

        return os.path.join(self.cache_dir, fname)

    @property
    def _is_cached(self):
        if not self.cache_dir:
            return False

        return os.path.exists(self._cache_path)

    def _write_to_cache(self, data):
        assert not self._is_cached
        assert self.cache_dir is not None

        with open(self._cache_path, 'wb') as fobj:
            fobj.write(data)

    def _read_from_cache(self):
        assert self._is_cached

        with open(self._cache_path, 'rb') as fobj:
            return fobj.read()

    def _write_results_s3(self, results):
        bucket = self._url_parsed.netloc

        key = self._url_parsed.path
        if key.startswith('/'):
            key = key[1:]

        with io.BytesIO() as fobj:
            with gzip.GzipFile(fileobj=fobj, mode='wb') as gzfile:
                gzfile.write(results.encode('utf-8'))
            fobj.seek(0, 0)

            self._client.upload_fileobj(
                fobj, bucket, key + '.json.gz',
                ExtraArgs={
                    'ContentType': 'application/json',
                    'ContentEncoding': 'gzip'
                }
            )

    def _write_results_local(self, results):
        outkey = self._url_parsed.path + '.json.gz'
        with gzip.open(outkey, 'wt', encoding='utf-8') as fobj:
            fobj.write(results)

    @cached_property
    def _times(self):
        name = os.path.basename(self._url_parsed.path).split('.')[0]
        start, end = name.split('-')

        return {
            'start': float(int(start)) / 1000000,
            'end': float(int(end)) / 1000000,
        }

    def write_results(self, results):
        '''
        Write the provided results (of transcription) to backing store, whether
        s3 or local file.
        '''

        ret = json.dumps({
            'url': self.url,
            'source': self.source,
            'lang': self.lang,
            'ingest_start_time': self._times['start'],
            'ingest_end_time': self._times['end'],
            'results': results,
        })

        if self._storage_mode == 's3':
            self._write_results_s3(ret)
        else:
            self._write_results_local(ret)

    def fetch(self):
        '''
        Fetch and return a bytes object containing the chunk's data.
        '''

        if self._is_cached:
            return self._read_from_cache()

        data = self._read_data()

        if self.cache_dir is not None:
            self._write_to_cache(data)

        return data

    def __len__(self):
        return 1

    def __iter__(self):
        yield {
            'url': self.url,
            'data': self.fetch(),
        }
