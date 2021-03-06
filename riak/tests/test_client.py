import platform
from six import PY2
from threading import Thread
from riak.riak_object import RiakObject
from riak.tests import DUMMY_HTTP_PORT, DUMMY_PB_PORT, RUN_POOL
from riak.tests.base import IntegrationTestBase

if PY2:
    from Queue import Queue
else:
    from queue import Queue

if platform.python_version() < '2.7':
    unittest = __import__('unittest2')
else:
    import unittest


class ClientTests(IntegrationTestBase, unittest.TestCase):
    def test_uses_client_id_if_given(self):
        if self.protocol == 'pbc':
            zero_client_id = "\0\0\0\0"
            c = self.create_client(client_id=zero_client_id)
            self.assertEqual(zero_client_id, c.client_id)
            c.close()
        else:
            pass

    def test_request_retries(self):
        # We guess at some ports that will be unused by Riak or
        # anything else.
        client = self.create_client(http_port=DUMMY_HTTP_PORT,
                                    pb_port=DUMMY_PB_PORT)

        # If retries are exhausted, the final result should also be an
        # error.
        self.assertRaises(IOError, client.ping)
        client.close()

    def test_request_retries_configurable(self):
        # We guess at some ports that will be unused by Riak or
        # anything else.
        client = self.create_client(http_port=DUMMY_HTTP_PORT,
                                    pb_port=DUMMY_PB_PORT)

        # Change the retry count
        client.retries = 10
        self.assertEqual(10, client.retries)

        # The retry count should be a thread local
        retries = Queue()

        def _target():
            retries.put(client.retries)
            retries.join()

        th = Thread(target=_target)
        th.start()
        self.assertEqual(3, retries.get(block=True))
        retries.task_done()
        th.join()

        # Modify the retries in a with statement
        with client.retry_count(5):
            self.assertEqual(5, client.retries)
            self.assertRaises(IOError, client.ping)
        client.close()

    def test_timeout_validation(self):
        bucket = self.client.bucket(self.bucket_name)
        key = self.key_name
        obj = bucket.new(key)
        for bad in [0, -1, False, "foo"]:
            with self.assertRaises(ValueError):
                self.client.get_buckets(timeout=bad)

            with self.assertRaises(ValueError):
                for i in self.client.stream_buckets(timeout=bad):
                    pass

            with self.assertRaises(ValueError):
                self.client.get_keys(bucket, timeout=bad)

            with self.assertRaises(ValueError):
                for i in self.client.stream_keys(bucket, timeout=bad):
                    pass

            with self.assertRaises(ValueError):
                self.client.put(obj, timeout=bad)

            with self.assertRaises(ValueError):
                self.client.get(obj, timeout=bad)

            with self.assertRaises(ValueError):
                self.client.delete(obj, timeout=bad)

            with self.assertRaises(ValueError):
                self.client.mapred([], [], bad)

            with self.assertRaises(ValueError):
                for i in self.client.stream_mapred([], [], bad):
                    pass

            with self.assertRaises(ValueError):
                self.client.get_index(bucket, 'field1_bin', 'val1', 'val4',
                                      timeout=bad)

            with self.assertRaises(ValueError):
                for i in self.client.stream_index(bucket, 'field1_bin', 'val1',
                                                  'val4', timeout=bad):
                    pass

    def test_multiget_bucket(self):
        """
        Multiget operations can be invoked on buckets.
        """
        keys = [self.key_name, self.randname(), self.randname()]
        for key in keys:
            if PY2:
                self.client.bucket(self.bucket_name)\
                    .new(key, encoded_data=key, content_type="text/plain")\
                    .store()
            else:
                self.client.bucket(self.bucket_name)\
                    .new(key, data=key,
                         content_type="text/plain").store()
        results = self.client.bucket(self.bucket_name).multiget(keys)
        for obj in results:
            self.assertIsInstance(obj, RiakObject)
            self.assertTrue(obj.exists)
            if PY2:
                self.assertEqual(obj.key, obj.encoded_data)
            else:
                self.assertEqual(obj.key, obj.data)

    def test_multiget_errors(self):
        """
        Unrecoverable errors are captured along with the bucket/key
        and not propagated.
        """
        keys = [self.key_name, self.randname(), self.randname()]
        client = self.create_client(http_port=DUMMY_HTTP_PORT,
                                    pb_port=DUMMY_PB_PORT)
        results = client.bucket(self.bucket_name).multiget(keys)
        for failure in results:
            self.assertIsInstance(failure, tuple)
            self.assertEqual(failure[0], 'default')
            self.assertEqual(failure[1], self.bucket_name)
            self.assertIn(failure[2], keys)
            if PY2:
                self.assertIsInstance(failure[3], StandardError)  # noqa
            else:
                self.assertIsInstance(failure[3], Exception)
        client.close()

    def test_multiget_notfounds(self):
        """
        Not founds work in multiget just the same as get.
        """
        keys = [("default", self.bucket_name, self.key_name),
                ("default", self.bucket_name, self.randname())]
        results = self.client.multiget(keys)
        for obj in results:
            self.assertIsInstance(obj, RiakObject)
            self.assertFalse(obj.exists)

    def test_multiget_pool_size(self):
        """
        The pool size for multigets can be configured at client initiation
        time. Multiget still works as expected.
        """
        client = self.create_client(multiget_pool_size=2)
        self.assertEqual(2, client._multiget_pool._size)

        keys = [self.key_name, self.randname(), self.randname()]
        for key in keys:
            if PY2:
                client.bucket(self.bucket_name)\
                    .new(key, encoded_data=key, content_type="text/plain")\
                    .store()
            else:
                client.bucket(self.bucket_name)\
                    .new(key, data=key, content_type="text/plain")\
                    .store()

        results = client.bucket(self.bucket_name).multiget(keys)
        for obj in results:
            self.assertIsInstance(obj, RiakObject)
            self.assertTrue(obj.exists)
            if PY2:
                self.assertEqual(obj.key, obj.encoded_data)
            else:
                self.assertEqual(obj.key, obj.data)
        client.close()

    @unittest.skipUnless(RUN_POOL, 'RUN_POOL is 0')
    def test_pool_close(self):
        """
        Iterate over the connection pool and close all connections.
        """
        # Do something to add to the connection pool
        self.test_multiget_bucket()
        if self.client.protocol == 'pbc':
            self.assertGreater(len(self.client._pb_pool.resources), 1)
        else:
            self.assertGreater(len(self.client._http_pool.resources), 1)
        # Now close them all up
        self.client.close()
        self.assertEqual(len(self.client._http_pool.resources), 0)
        self.assertEqual(len(self.client._pb_pool.resources), 0)
