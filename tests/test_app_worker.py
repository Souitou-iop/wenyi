from __future__ import annotations

import json
import os
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

from trans_novel.app_worker import EventWriter, WorkerRequest, run_worker


class TestEventWriter(unittest.TestCase):
    def test_writes_one_json_object_per_line(self):
        stream = StringIO()
        writer = EventWriter("task-1", stream=stream)

        writer.emit("phase", phase="preparing", label="准备中")

        lines = stream.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertEqual(event["protocolVersion"], 1)
        self.assertEqual(event["taskID"], "task-1")
        self.assertEqual(event["type"], "phase")
        self.assertEqual(event["phase"], "preparing")


class TestRunWorker(unittest.TestCase):
    def test_completed_event_contains_outputs_and_isolated_state_directory(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "book.txt")
            config = os.path.join(root, "config.yaml")
            output = os.path.join(root, "output", "book.zh.epub")
            state = os.path.join(root, "state", "book-id")
            with open(source, "w", encoding="utf-8") as f:
                f.write("hello")
            with open(config, "w", encoding="utf-8") as f:
                f.write("llm: {}")
            stream = StringIO()
            request = WorkerRequest(
                task_id="task-1",
                input_path=source,
                output_path=output,
                state_dir=state,
                config_path=config,
            )

            class FakeOrchestrator:
                def __init__(self, cfg):
                    self.cfg = cfg

                def run_all(self, input_path, **kwargs):
                    self.assertions = kwargs
                    kwargs["phase"]("translating", "翻译中")
                    kwargs["progress"](2, 4, "第 1 章")
                    return {
                        "outputs": [output],
                        "report": {"summary": {"chapters_done": 1}},
                        "store": type("Store", (), {"run_dir": state})(),
                    }

            with (
                patch("trans_novel.app_worker.Config.load") as load,
                patch("trans_novel.app_worker.Orchestrator", FakeOrchestrator),
            ):
                cfg = load.return_value
                cfg.state_dir = "old"
                code = run_worker(request, stream=stream)

            self.assertEqual(code, 0)
            self.assertEqual(cfg.state_dir, state)
            events = [json.loads(line) for line in stream.getvalue().splitlines()]
            self.assertEqual(events[0]["type"], "ready")
            self.assertTrue(any(e["type"] == "progress" and e["fraction"] == 0.5 for e in events))
            self.assertEqual(events[-1]["type"], "completed")
            self.assertEqual(events[-1]["outputs"], [output])


if __name__ == "__main__":
    unittest.main()
