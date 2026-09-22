import unittest
import os
import tempfile
import time
from store.database import Database
from store.file_store import FileStore


class TestFileStore(unittest.TestCase):
    def setUp(self):
        self.temp_db_file = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.temp_db_file.close()
        self.db = Database(self.temp_db_file.name)
        self.temp_dir = tempfile.mkdtemp()
        self.store = FileStore(self.db, download_dir=self.temp_dir)

    def tearDown(self):
        try:
            os.remove(self.temp_db_file.name)
        except Exception:
            pass

    def test_record_and_get_file(self):
        fid = self.store.record_file(
            file_id="tg_12345",
            file_name="test.pdf",
            file_size=1024,
            mime_type="application/pdf",
            frontend="telegram",
            group_id="group_1",
            user_id="user_1",
            message_id="msg_999",
            local_path="/tmp/test.pdf",
            url="http://example.com/test.pdf",
        )
        self.assertGreater(fid, 0)

        record = self.store.get_file(fid)
        self.assertIsNotNone(record)
        self.assertEqual(record["file_name"], "test.pdf")
        self.assertEqual(record["mime_type"], "application/pdf")
        self.assertEqual(record["message_id"], "msg_999")

        files_by_msg = self.store.get_files_by_message("msg_999")
        self.assertEqual(len(files_by_msg), 1)
        self.assertEqual(files_by_msg[0]["id"], fid)

    def test_get_recent_files(self):
        self.store.record_file(
            file_id="f1",
            file_name="one.docx",
            frontend="onebot",
            group_id="100",
            user_id="200",
            message_id="m1",
        )
        time.sleep(0.01)
        self.store.record_file(
            file_id="f2",
            file_name="two.pdf",
            frontend="onebot",
            group_id="100",
            user_id="200",
            message_id="m2",
        )

        recent = self.store.get_recent_files(frontend="onebot", group_id="100", limit=5)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["file_name"], "two.pdf")
        self.assertEqual(recent[1]["file_name"], "one.docx")

    def test_find_file(self):
        fid = self.store.record_file(
            file_id="file_abc",
            file_name="年度报告.pdf",
            frontend="telegram",
            group_id="g1",
            user_id="u1",
            message_id="m3",
        )

        # By ID
        res1 = self.store.find_file(str(fid), group_id="g1")
        self.assertIsNotNone(res1)
        self.assertEqual(res1["file_id"], "file_abc")

        # By file_id
        res2 = self.store.find_file("file_abc", group_id="g1")
        self.assertIsNotNone(res2)
        self.assertEqual(res2["id"], fid)

        # By name substring
        res3 = self.store.find_file("年度报告", group_id="g1")
        self.assertIsNotNone(res3)
        self.assertEqual(res3["file_name"], "年度报告.pdf")

    def test_save_and_record_local_file(self):
        dummy_path = os.path.join(self.temp_dir, "sample.txt")
        with open(dummy_path, "w", encoding="utf-8") as f:
            f.write("Hello FileStore!")

        info = {
            "name": "sample.txt",
            "path": dummy_path,
        }
        rec = self.store.save_and_record_file(
            info,
            frontend="telegram",
            user_id="u1",
            message_id="m4",
        )
        self.assertIsNotNone(rec.get("id"))
        self.assertEqual(rec["file_name"], "sample.txt")
        self.assertEqual(rec["local_path"], dummy_path)
        self.assertGreater(rec["file_size"], 0)


if __name__ == "__main__":
    unittest.main()
