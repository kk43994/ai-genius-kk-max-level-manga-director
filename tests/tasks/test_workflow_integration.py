"""Opt-in module 3 + 7 + 8 integration with a free in-process provider fake."""

import io
import os
from pathlib import Path
import unittest

import backend
import test_store_integration as storage_tests

Store = storage_tests.Store

if os.environ.get("ASSET_LAB_WORKFLOW_MODULE_ROOT"):
    backend.__path__.append(str(Path(os.environ["ASSET_LAB_WORKFLOW_MODULE_ROOT"]).resolve() / "backend"))
try:
    from PIL import Image
    from backend.workflow import WorkflowOutputStore, WorkflowRepository, WorkflowService
except ImportError:
    WorkflowService = None

from backend.tasks import DownloadArtifact


@unittest.skipIf(Store is None or WorkflowService is None, "shared storage/workflow modules and dependencies are not installed")
class WorkflowTaskTests(unittest.TestCase):
    new_service = storage_tests.SharedStoreTests.new_service

    def setUp(self):
        storage_tests.SharedStoreTests.setUp(self)
        self.workflow = WorkflowService(WorkflowRepository(self.store), tasks=self.f.service)
        self.project = self.workflow.create_project(self.f.ctx, {"name": "合成任务联调", "description": "无真实内容"})
        self.plan = self.workflow.save_plan(self.f.ctx, self.project["id"], {
            "expectedVersion": 0, "stylePrompt": "测试风格一", "entities": [
                {"id": "entity_one", "category": "character", "name": "合成人物", "description": "测试设定", "origin": "manual"}]})
        self.f.service.inputs = self.workflow
        self.f.service.outputs = WorkflowOutputStore(self.workflow, self.repository)
        raw = io.BytesIO()
        Image.new("RGB", (16, 16), (30, 80, 40)).save(raw, "PNG")
        self.f.providers.artifacts = [DownloadArtifact(raw.getvalue(), "image/png")]
        self.f.providers.lookup_result = {"status": "completed"}

    def prepare(self, key="workflow-prepare-1", **kwargs):
        return self.f.prepare(key, projectId=self.project["id"], **kwargs)

    def finish(self, prepared, key="workflow-submit-1"):
        task = self.f.submit(prepared, key)["task"]
        return self.f.service.recover(self.f.ctx, task["id"], task["version"])["task"]

    def edit_style(self):
        plan = self.workflow.get_plan(self.f.ctx, self.project["id"])
        entities = [{k: v for k, v in row.items() if k in {"id", "category", "name", "description", "origin"}}
                    for row in plan["entities"]]
        self.workflow.save_plan(self.f.ctx, self.project["id"], {
            "expectedVersion": plan["version"], "stylePrompt": "测试风格二", "entities": entities})

    def test_snapshot_survives_real_task_to_workflow_output_bridge(self):
        prepared = self.prepare()
        self.assertEqual(prepared["task"]["workflowSnapshot"]["styleVersion"], self.plan["styleVersion"])
        task = self.finish(prepared)
        self.assertEqual(task["status"], "completed", task.get("error"))
        output = task["outputs"][0]
        revision = self.workflow.get_revision(self.f.ctx, output["revisionId"], require_approved=False)
        self.assertEqual(output["assetId"], revision["assetId"])
        self.assertEqual(revision["styleVersion"], task["workflowSnapshot"]["styleVersion"])
        self.assertEqual(revision["review"], "pending")
        self.assertEqual(revision["status"], "ready")

    def test_plan_changed_while_remote_task_running_keeps_old_result_out_of_current_assets(self):
        prepared = self.prepare()
        task = self.f.submit(prepared)["task"]
        self.edit_style()
        result = self.f.service.recover(self.f.ctx, task["id"], task["version"])["task"]
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(result["error"]["code"], "WORKFLOW_VERSION_CHANGED")
        self.assertEqual(result["workflowSnapshot"], prepared["task"]["workflowSnapshot"])
        self.assertEqual(self.store.list(self.f.ctx, "workflow.revisions")["items"], [])
        self.assertEqual(self.f.providers.submit_count, 1)

    def test_plan_change_in_final_output_race_is_recorded_stale_by_workflow(self):
        prepared = self.prepare()
        original_store = self.f.service.outputs
        parent = self
        class RacingOutputStore:
            def put(self, *args, **kwargs):
                parent.edit_style()
                return original_store.put(*args, **kwargs)

            def read(self, *args, **kwargs):
                return original_store.read(*args, **kwargs)
        self.f.service.outputs = RacingOutputStore()
        task = self.finish(prepared)
        self.assertEqual(task["status"], "needs_attention")
        self.assertEqual(task["error"]["code"], "WORKFLOW_VERSION_CHANGED")
        rows = self.store.list(self.f.ctx, "workflow.revisions")["items"]
        self.assertEqual(len(rows), 1)
        revision = self.workflow.get_revision(self.f.ctx, rows[0]["id"], require_approved=False)
        self.assertEqual(revision["status"], "stale")
        self.assertEqual(revision["styleVersion"], prepared["task"]["workflowSnapshot"]["styleVersion"])
        self.assertEqual(revision["review"], "pending")
        self.assertEqual(self.f.providers.submit_count, 1)

    def test_next_stage_reads_reviewed_original_owner_and_snapshot(self):
        style_task = self.finish(self.prepare())
        output = style_task["outputs"][0]
        asset = next(row for row in self.workflow.list_assets(self.f.ctx, self.project["id"])["items"] if row["id"] == output["assetId"])
        self.workflow.review(self.f.ctx, output["assetId"], {
            "revisionId": output["revisionId"], "sha256": output["sha256"],
            "decision": "approved", "note": "人工测试审核通过", "expectedVersion": asset["version"]})
        image2 = self.prepare("workflow-image2-prepare", recipe="image2_asset", sourceRevisionIds=[output["revisionId"]])
        self.assertEqual(image2["task"]["workflowSnapshot"]["sourceHashes"], {output["revisionId"]: output["sha256"]})
        result = self.finish(image2, "workflow-image2-submit")
        self.assertEqual(result["status"], "completed", result.get("error"))
        self.assertEqual(result["review"], "pending")


if __name__ == "__main__":
    unittest.main()
