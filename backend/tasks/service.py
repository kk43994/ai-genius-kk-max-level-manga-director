"""Durable state machine. No network call occurs inside a database transaction.

The only call that can generate is submit(), after a committed attempted marker.
Every recovery path is lookup/download only, including after a service restart.
"""

import hashlib
import hmac
import secrets
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from .errors import TaskError, provider_failure
from .model import (HASH_RE, OWNER_KEYS, TERMINAL, cost, decode_cursor,
                    digest, encode_cursor, merge_receipt, opaque, owner_match,
                    parse_time, public_task, receipt, safe_prepared, selection_revision,
                    tenant, timestamp, utcnow, validate_spec, version, workflow_snapshot)
from .ports import DownloadArtifact, TaskPolicy


class TaskService:
    def __init__(self, *, repository, providers, selections, spaces, inputs, outputs,
                 policy: TaskPolicy, clock=utcnow):
        if not isinstance(policy.confirmation_key, bytes) or len(policy.confirmation_key) < 32:
            raise ValueError("Task confirmation_key must be a persistent key of at least 32 bytes")
        if type(policy.allow_paid_submission) is not bool or type(policy.video_generation) is not bool:
            raise ValueError("Task generation flags must be explicit booleans")
        if any(type(value) is not int or value <= 0 for value in (policy.confirmation_ttl_seconds, policy.lease_seconds, policy.max_outputs, policy.max_output_bytes)):
            raise ValueError("Invalid task limits")
        self.repository, self.providers = repository, providers
        self.selections, self.spaces, self.inputs, self.outputs = selections, spaces, inputs, outputs
        self.policy, self.clock = policy, clock

    def _now(self):
        return timestamp(self.clock())

    def _get(self, tx, ctx, task_id):
        opaque(task_id, "任务")
        task = tx.get_task(task_id)
        if task is None or task.get("ownership", {}).get("tenantId") != tenant(ctx):
            raise TaskError("NOT_FOUND", "任务不存在。", 404)
        return deepcopy(task)

    def _save(self, tx, task):
        expected = task["version"]
        task["version"] += 1
        task["updatedAt"] = self._now()
        tx.put_task(deepcopy(task), expected)

    def _expect(self, task, expected):
        if task["version"] != version(expected):
            raise TaskError("VERSION_CONFLICT", "任务已更新，请刷新任务状态后继续。", 409)

    def _idempotency(self, tx, scope, key, request_hash):
        if not isinstance(key, str) or not 8 <= len(key) <= 200 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise TaskError("IDEMPOTENCY_KEY_REQUIRED", "请提供有效的 Idempotency-Key。", 422)
        key_digest = hashlib.sha256(key.encode()).hexdigest()
        record = tx.get_request(scope, key_digest)
        if record and record.get("requestHash") != request_hash:
            raise TaskError("IDEMPOTENCY_CONFLICT", "同一请求编号的内容已改变。", 409)
        return key_digest, record

    def _request(self, tx, scope, key_digest, request_hash, task):
        tx.put_request(scope, key_digest, {"requestHash": request_hash, "taskId": task["id"]})

    def _selection(self, ctx):
        tenant(ctx)
        selected = deepcopy(dict(self.selections.get_selection(ctx)))
        selection_revision(selected.get("revision"))
        return selected

    def _owner(self, ctx, selected):
        account_id, space_id = selected.get("providerAccountId"), selected.get("spaceId")
        if not account_id or not space_id:
            raise TaskError("SELECTION_REQUIRED", "请先选择自己的 LibTV 登录账号与空间。", 409)
        opaque(account_id, "账号")
        opaque(space_id, "空间")
        account = self.providers.get_account(ctx, account_id)
        identity = account.get("identity", {})
        if account.get("id") != account_id or account.get("provider") != "libtv" or not identity.get("verified") or not identity.get("issuer") or not identity.get("subject"):
            raise TaskError("IDENTITY_UNVERIFIED", "官方登录身份尚未核实，不能创建生成任务。", 409)
        if account.get("removedAt") or account.get("authorization", {}).get("state") != "connected":
            raise TaskError("ORIGINAL_AUTHORIZATION_REQUIRED", "请先完成所选账号的官方授权。", 409)
        space = self.spaces.get_space(ctx, account_id, space_id)
        if space.get("id") != space_id or space.get("kind") not in {"personal", "team"} or space.get("access") != "available":
            raise TaskError("SPACE_UNAVAILABLE", "所选空间的访问权限尚未确认。", 409)
        return {"tenantId": tenant(ctx), "provider": "libtv", "providerAccountId": account_id,
                "providerIssuer": str(identity["issuer"]), "providerSubject": str(identity["subject"]),
                "spaceId": space_id, "spaceKind": space["kind"], "boundAt": self._now(),
                "accountLabelAtCreation": str(account.get("label") or "LibTV 账号")[:200],
                "spaceNameAtCreation": str(space.get("name") or "原空间")[:200]}

    def _identity(self, client, owner, ctx):
        actual = client.identity()
        expected = {"provider": owner["provider"], "providerAccountId": owner["providerAccountId"],
                    "issuer": owner["providerIssuer"], "subject": owner["providerSubject"],
                    "spaceId": owner["spaceId"], "spaceKind": owner["spaceKind"]}
        if (not isinstance(actual, dict) or actual.get("verified") is not True
                or actual.get("issuer") != expected["issuer"] or actual.get("subject") != expected["subject"]
                or any(k in actual and actual[k] != v for k, v in expected.items())):
            raise TaskError("OWNERSHIP_MISMATCH", "官方身份或空间与任务原归属不一致，已停止操作。", 409)
        # Official identity replies need not contain a workspace. Check access
        # independently through the space service using the ORIGINAL account.
        space = self.spaces.get_space(ctx, owner["providerAccountId"], owner["spaceId"])
        if space.get("id") != owner["spaceId"] or space.get("kind") != owner["spaceKind"] or space.get("access") != "available":
            raise TaskError("SPACE_ACCESS_REVOKED", "原任务空间已不可访问，请恢复原空间权限。", 409)

    def _client(self, ctx, owner):
        if owner["tenantId"] != tenant(ctx):
            raise TaskError("NOT_FOUND", "任务不存在。", 404)
        client = self.providers.client_for(ctx, deepcopy(owner))
        self._identity(client, owner, ctx)
        return client

    def _validate_inputs(self, ctx, spec, owner):
        # The workflow adapter verifies the project/entity and reads immutable
        # revisions from shared storage. TaskService checks the security snapshot.
        checked = self.inputs.validate_task_inputs(ctx, deepcopy(spec), deepcopy(owner))
        if not isinstance(checked, dict) or checked.get("projectTenantId") != tenant(ctx):
            raise TaskError("NOT_FOUND", "项目或参考素材不存在。", 404)
        normalized = validate_spec(checked.get("spec"))
        if digest(normalized) != digest(spec):
            raise TaskError("SOURCE_CHANGED", "项目或任务参数已变化，请重新准备任务。", 409)
        sources = checked.get("sources")
        if not isinstance(sources, list) or [s.get("revisionId") for s in sources if isinstance(s, dict)] != spec["sourceRevisionIds"]:
            raise TaskError("SOURCE_CHANGED", "参考版本记录不完整。", 409)
        snapshot = []
        for source in sources:
            if not owner_match(source.get("ownership", {}), owner):
                raise TaskError("OWNERSHIP_MISMATCH", "参考素材必须属于任务的原账号与空间。", 409)
            if source.get("review") != "approved" or source.get("stale") is not False:
                raise TaskError("SOURCE_REVIEW_REQUIRED", "参考素材尚未通过人工审核，或来源已失效。", 409)
            sha = source.get("sha256")
            if not isinstance(sha, str) or not HASH_RE.fullmatch(sha):
                raise TaskError("SOURCE_CHANGED", "参考素材缺少已校验的文件摘要。", 409)
            snapshot.append({"revisionId": source["revisionId"], "sha256": sha,
                             "ownership": {k: owner[k] for k in OWNER_KEYS}})
        return {"spec": normalized, "sources": snapshot,
                "workflowSnapshot": workflow_snapshot(checked.get("workflowSnapshot"), snapshot)}

    def _saved_inputs(self, task):
        saved = task.get("inputs", {})
        workflow_snapshot(saved.get("workflowSnapshot"), saved.get("sources", []))
        if digest(saved) != task.get("inputHash") or digest(saved.get("spec")) != digest(task.get("spec")):
            raise TaskError("SOURCE_CHANGED", "任务保存的输入摘要不一致，已停止处理。", 409)

    def _revalidate_inputs(self, ctx, task):
        self._saved_inputs(task)
        try:
            current = self._validate_inputs(ctx, task["spec"], task["ownership"])
        except Exception as exc:
            if getattr(exc, "code", None) in {"VERSION_CONFLICT", "NOT_FOUND", "VALIDATION_FAILED"}:
                raise TaskError("WORKFLOW_VERSION_CHANGED", "原任务的资产清单或来源已变化，不能作为当前版本收取或提交。", 409) from None
            raise
        if current["sources"] != task["inputs"]["sources"]:
            raise TaskError("SOURCE_CHANGED", "参考文件摘要已变化，已停止处理原任务。", 409)
        if current["workflowSnapshot"] != task["inputs"]["workflowSnapshot"]:
            raise TaskError("WORKFLOW_VERSION_CHANGED", "资产清单或风格已换版。原任务记录仍保留，不能作为当前版本提交或收取。", 409)
        if digest(current) != task["inputHash"]:
            raise TaskError("SOURCE_CHANGED", "参考文件摘要已变化，已停止处理原任务。", 409)

    def _lease(self, task, action):
        lease = task.get("lease")
        if lease and parse_time(lease["expiresAt"]) > self.clock():
            raise TaskError("TASK_BUSY", "任务正在处理，请稍后刷新状态。", 409)
        lease = {"token": secrets.token_hex(20), "action": action,
                 "expiresAt": timestamp(self.clock() + timedelta(seconds=self.policy.lease_seconds))}
        task["lease"] = lease
        return deepcopy(lease)

    def _owns(self, task, lease):
        return bool(task.get("lease") and task["lease"]["token"] == lease["token"])

    def _confirmation_basis(self, task, selected_revision, expires_at, target_version):
        return {"taskId": task["id"], "version": target_version, "ownership": task["ownership"],
                "inputHash": task["inputHash"], "prepared": task["prepared"],
                "selectionRevision": selected_revision, "expiresAt": expires_at}

    def _set_confirmation(self, task, selected_revision):
        expires = timestamp(self.clock() + timedelta(seconds=self.policy.confirmation_ttl_seconds))
        basis = self._confirmation_basis(task, selected_revision, expires, task["version"] + 1)
        task["confirmation"] = {"digest": digest(basis), "expiresAt": expires,
                                "version": task["version"] + 1, "selectionRevision": selected_revision}

    def _token(self, task):
        return hmac.new(self.policy.confirmation_key, task["confirmation"]["digest"].encode(), hashlib.sha256).hexdigest()

    def _response(self, task):
        confirmation = None
        saved = task.get("confirmation")
        if saved and task["status"] == "draft" and saved["version"] == task["version"]:
            confirmation = {"token": self._token(task), "expiresAt": saved["expiresAt"],
                            "summary": {"taskId": task["id"], "ownership": deepcopy(task["ownership"]),
                                        "recipe": task["recipe"], "prompt": task["spec"]["prompt"],
                                        "settings": deepcopy(task["spec"]["settings"]),
                                        "sourceRevisionIds": deepcopy(task["sourceRevisionIds"]),
                                        "inputHash": task["inputHash"], "modelKey": task["prepared"]["modelKey"],
                                        "schemaHash": task["prepared"]["schemaHash"],
                                        "count": task["prepared"]["count"], "cost": deepcopy(task["cost"])}}
        return {"task": public_task(task), "confirmation": confirmation, "cost": deepcopy(task["cost"])}

    def prepare(self, ctx, spec, expectedSelectionRevision, idempotencyKey):
        tenant(ctx)
        spec = validate_spec(spec)
        self._assert_new_prompt(spec)
        expectedSelectionRevision = selection_revision(expectedSelectionRevision)
        request_hash = digest({"spec": spec, "selectionRevision": expectedSelectionRevision})
        with self.repository.transaction(ctx) as tx:
            key, previous = self._idempotency(tx, "prepare", idempotencyKey, request_hash)
            if previous:
                return self._response(self._get(tx, ctx, previous["taskId"]))
        selected = self._selection(ctx)
        if selected["revision"] != expectedSelectionRevision:
            raise TaskError("SELECTION_CHANGED", "当前账号或空间已变化，请重新核对新任务归属。", 409)
        owner = self._owner(ctx, selected)
        inputs = self._validate_inputs(ctx, spec, owner)
        now = self._now()
        task = {"id": "task_" + uuid4().hex, "version": 1, "ownership": owner,
                "projectId": spec["projectId"], "entityId": spec["entityId"], "recipe": spec["recipe"],
                "spec": deepcopy(spec), "sourceRevisionIds": spec["sourceRevisionIds"],
                "inputs": inputs, "inputHash": digest(inputs), "status": "preparing",
                "submissionAttempted": False, "providerReceipt": None, "prepared": None,
                "confirmation": None, "cost": cost(None), "outputs": [], "review": "pending",
                "error": None, "createdAt": now, "updatedAt": now, "remoteStatus": "unknown"}
        lease = self._lease(task, "prepare")
        with self.repository.transaction(ctx) as tx:
            key, previous = self._idempotency(tx, "prepare", idempotencyKey, request_hash)
            if previous:
                return self._response(self._get(tx, ctx, previous["taskId"]))
            tx.assert_selection(expectedSelectionRevision, owner)
            tx.put_task(deepcopy(task), None)
            self._request(tx, "prepare", key, request_hash, task)
        try:
            client = self._client(ctx, owner)
            raw = client.prepare({**deepcopy(spec), "ownership": deepcopy(owner),
                                  "requestHash": task["inputHash"], "sources": deepcopy(inputs["sources"]),
                                  "localTaskId": task["id"]})
            prepared = safe_prepared(raw, task["inputHash"], self.policy.max_outputs)
        except Exception as exc:
            return self._operation_failure(ctx, task["id"], lease, exc)
        with self.repository.transaction(ctx) as tx:
            current = self._get(tx, ctx, task["id"])
            if not self._owns(current, lease):
                return self._response(current)
            current.update(prepared=prepared, providerReceipt=prepared["providerReceipt"],
                           preparedAt=self._now(), status="draft", lease=None, cost=prepared["cost"], error=None)
            self._set_confirmation(current, selected["revision"])
            self._save(tx, current)
            return self._response(current)

    def confirm(self, ctx, task_id, expectedVersion):
        """Explicitly reconfirm the original owner; never bind the current choice."""
        selected = self._selection(ctx)
        with self.repository.transaction(ctx) as tx:
            task = self._get(tx, ctx, task_id)
            self._expect(task, expectedVersion)
            if task["status"] != "draft" or task["submissionAttempted"]:
                raise TaskError("TASK_NOT_CONFIRMABLE", "此任务当前不能重新确认提交。", 409)
            self._assert_new_prompt(task['spec'])
            tx.assert_selection(selected["revision"])
            self._set_confirmation(task, selected["revision"])
            self._save(tx, task)
            return self._response(task)

    def _check_confirmation(self, task, token, selected):
        self._saved_inputs(task)
        self._assert_new_prompt(task['spec'])
        saved = task.get("confirmation")
        if not saved or saved["version"] != task["version"] or not isinstance(token, str) or not hmac.compare_digest(self._token(task), token):
            raise TaskError("CONFIRMATION_REQUIRED", "请先核对任务内容与原账号，再确认提交。", 409)
        if parse_time(saved["expiresAt"]) <= self.clock():
            raise TaskError("CONFIRMATION_EXPIRED", "确认已过期，请重新核对任务。", 409)
        expected = self._confirmation_basis(task, saved["selectionRevision"], saved["expiresAt"], task["version"])
        if digest(expected) != saved["digest"]:
            raise TaskError("CONFIRMATION_CHANGED", "任务内容已变化，请重新准备。", 409)
        if selected["revision"] != saved["selectionRevision"]:
            raise TaskError("SELECTION_CHANGED", "当前选择已改变。此任务仍属于原账号和空间，请重新确认原归属。", 409,
                            details={"taskId": task["id"], "providerAccountId": task["ownership"]["providerAccountId"],
                                     "spaceId": task["ownership"]["spaceId"]})
        quote = task["cost"]
        if quote.get("expiresAt") and parse_time(quote["expiresAt"]) <= self.clock():
            raise TaskError("QUOTE_EXPIRED", "原报价已过期，请重新准备任务。", 409)

    @staticmethod
    def _assert_new_prompt(spec):
        # New generation must use reviewed requirements. Previously submitted
        # receipts remain recoverable even if their old prompts were inadequate.
        prompt = spec.get('prompt', '')
        if '请填写希望采用的视觉风格' in prompt or '生成完整的风格候选图。' in prompt:
            raise TaskError('PROMPT_REVIEW_REQUIRED', '旧的通用或占位提示词不能提交，请先根据剧本编写并核对当前资产提示词。', 409)

    def submit(self, ctx, task_id, expectedVersion, confirmationToken, idempotencyKey):
        tenant(ctx)
        request_hash = digest({"id": task_id, "expectedVersion": expectedVersion,
                               "confirmationToken": confirmationToken})
        with self.repository.transaction(ctx) as tx:
            key, previous = self._idempotency(tx, "submit", idempotencyKey, request_hash)
            if previous:
                return {"task": public_task(self._get(tx, ctx, previous["taskId"]))}
            task = self._get(tx, ctx, task_id)
            self._expect(task, expectedVersion)
            if not self.policy.allow_paid_submission:
                raise TaskError("PAID_SUBMISSION_DISABLED", "开发验收期间生成提交已关闭，任务草稿已保留。", 403)
            if task["recipe"] not in {"mj_style", "image25_style", "image2_asset", "image25_asset", "nano_refine", "storyboard_image", "image25_storyboard", "script_analysis"}:
                raise TaskError("VIDEO_GENERATION_DISABLED", "正式视频生成仍暂停。", 403)
            if task["submissionAttempted"]:
                raise TaskError("SUBMISSION_ALREADY_ATTEMPTED", "此任务已尝试提交，只能查回原任务。", 409)
            if task["status"] != "draft":
                raise TaskError("TASK_NOT_SUBMITTABLE", "请先处理任务提示并重新确认。", 409)
        # Read selection outside the task DB transaction. The revision is only a
        # confirmation guard; a later selection change cannot change this owner.
        selected = self._selection(ctx)
        with self.repository.transaction(ctx) as tx:
            key, previous = self._idempotency(tx, "submit", idempotencyKey, request_hash)
            if previous:
                return {"task": public_task(self._get(tx, ctx, previous["taskId"]))}
            task = self._get(tx, ctx, task_id)
            self._expect(task, expectedVersion)
            self._check_confirmation(task, confirmationToken, selected)
            tx.assert_selection(selected["revision"])
            lease = self._lease(task, "submit")
            task.update(status="preparing", error=None, confirmation=None)
            self._save(tx, task)
            self._request(tx, "submit", key, request_hash, task)
        try:
            client = self._client(ctx, task["ownership"])
            self._revalidate_inputs(ctx, task)
            # Fresh official verification immediately before the durable marker.
            self._identity(client, task["ownership"], ctx)
        except Exception as exc:
            return self._operation_failure(ctx, task_id, lease, exc)
        with self.repository.transaction(ctx) as tx:
            task = self._get(tx, ctx, task_id)
            if not self._owns(task, lease) or parse_time(task["lease"]["expiresAt"]) <= self.clock():
                raise TaskError("LEASE_LOST", "处理权已变化，未再次提交。请刷新任务状态。", 409)
            # A unique server key is never reused for another task or attempt.
            task.update(status="submitting", submissionAttempted=True,
                        submissionKey="generation_" + task["id"], submittedAt=self._now(),
                        confirmation=None, error=None)
            self._save(tx, task)
        try:
            result = client.submit({**deepcopy(task["prepared"]), "spec": deepcopy(task["spec"]),
                                    "sources": deepcopy(task["inputs"]["sources"]),
                                    "ownership": deepcopy(task["ownership"]), "localTaskId": task["id"]},
                                   task["submissionKey"])
            if not isinstance(result, dict):
                raise TaskError("SUBMISSION_UNKNOWN", "官方提交响应未确认。", 409)
            ref = merge_receipt(task.get("providerReceipt"), result.get("providerReceipt"))
            state = result.get("status")
            if not ref or state not in {"queued", "running", "completed"}:
                error = TaskError("SUBMISSION_UNKNOWN", "官方提交响应未确认。", 409)
                error.provider_receipt = ref
                raise error
        except Exception as exc:
            return self._operation_failure(ctx, task_id, lease, exc, attempted=True)
        with self.repository.transaction(ctx) as tx:
            current = self._get(tx, ctx, task_id)
            # A late official response is still evidence, even if cancellation or
            # an expired lease prevented further processing. Never discard it.
            current["providerReceipt"] = merge_receipt(current.get("providerReceipt"), ref)
            current["remoteStatus"] = state
            if self._owns(current, lease) and current["status"] not in TERMINAL:
                current.update(status="queued" if state == "completed" else state, lease=None, error=None)
            self._save(tx, current)
            return {"task": public_task(current)}

    def _operation_failure(self, ctx, task_id, lease, exc, *, attempted=False):
        # Developer diagnostics without upstream messages, payloads or signed URLs.
        import logging
        import traceback
        from pathlib import Path
        from .errors import PREPARATION_CODES, AUTH_CODES
        code = getattr(exc, 'code', None)
        safe_code = code if code in PREPARATION_CODES or code in AUTH_CODES else 'UNCLASSIFIED'
        locations = ['%s:%s:%s' % (Path(f.filename).name, f.lineno, f.name)
                     for f in traceback.extract_tb(exc.__traceback__)[-6:]]
        logging.getLogger(__name__).error('Task operation failed: code=%s type=%s locations=%s',
            safe_code, type(exc).__name__, ' > '.join(locations))
        with self.repository.transaction(ctx) as tx:
            task = self._get(tx, ctx, task_id)
            # Explicitly typed error receipts only; never parse text or URLs.
            evidence = getattr(exc, "provider_receipt", None)
            if evidence:
                try:
                    task["providerReceipt"] = merge_receipt(task.get("providerReceipt"), evidence)
                except TaskError:
                    evidence = None
            if self._owns(task, lease):
                status, error = provider_failure(exc, attempted=attempted or task["submissionAttempted"])
                if getattr(exc, 'code', None) == 'REFERENCE_PREFLIGHT_REJECTED' and (not evidence or evidence != task.get('providerReceipt') or evidence.get('taskId') or not evidence.get('nodeId')):
                    status, error = 'needs_attention', {'code':'PROVIDER_RECEIPT_MISMATCH',
                        'message':'拒绝记录与原节点回执不一致，仍需核对原任务。', 'retryable':False, 'details':{}}
                if isinstance(exc, TaskError) and exc.code in {"SOURCE_CHANGED", "SOURCE_REVIEW_REQUIRED", "WORKFLOW_VERSION_CHANGED", "WORKFLOW_SNAPSHOT_MISSING", "PROVIDER_RECEIPT_MISMATCH", "OUTPUT_INVALID", "OUTPUT_STORE_UNVERIFIED"}:
                    status, error = "needs_attention", exc.public()
                task.update(status=status, error=error, lease=None, confirmation=None)
                self._save(tx, task)
            elif evidence:
                self._save(tx, task)
            return self._response(task)

    def get(self, ctx, task_id):
        tenant(ctx)
        with self.repository.transaction(ctx) as tx:
            return public_task(self._get(tx, ctx, task_id))

    def list(self, ctx, *, projectId=None, providerAccountId=None, spaceId=None, cursor=None, limit=50):
        tenant_id = tenant(ctx)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise TaskError("VALIDATION_FAILED", "分页数量必须在 1 到 100 之间。", 422)
        for value in (projectId, providerAccountId, spaceId):
            if value is not None:
                opaque(value)
        after = decode_cursor(cursor) if cursor else None
        with self.repository.transaction(ctx) as tx:
            tasks = [t for t in tx.list_tasks() if t.get("ownership", {}).get("tenantId") == tenant_id
                     and (projectId is None or t["projectId"] == projectId)
                     and (providerAccountId is None or t["ownership"]["providerAccountId"] == providerAccountId)
                     and (spaceId is None or t["ownership"]["spaceId"] == spaceId)
                     and (after is None or t["id"] > after)]
        tasks.sort(key=lambda t: t["id"])
        return {"items": [public_task(t) for t in tasks[:limit]],
                "nextCursor": encode_cursor(tasks[limit - 1]["id"]) if len(tasks) > limit else None}

    def recover(self, ctx, task_id, expectedVersion):
        tenant(ctx)
        with self.repository.transaction(ctx) as tx:
            task = self._get(tx, ctx, task_id)
            self._expect(task, expectedVersion)
            if task["status"] in TERMINAL:
                return {"task": public_task(task)}
            lease = self._lease(task, "recover")
            if not task["submissionAttempted"] and not task.get("prepared"):
                raise TaskError("PREPARATION_UNCONFIRMED", "原准备步骤未确认，不能自动重做或提交。", 409)
            if task["submissionAttempted"] and not task.get("providerReceipt"):
                task.update(status="needs_attention", lease=None, confirmation=None,
                            error={"code": "ORIGINAL_RECEIPT_REQUIRED", "message": "没有可验证的官方任务引用。请核对原任务；系统不会再次提交。",
                                   "retryable": False, "details": {}})
                self._save(tx, task)
                return {"task": public_task(task)}
            task.update(error=None, confirmation=None)
            self._save(tx, task)
        try:
            self._saved_inputs(task)
            client = self._client(ctx, task["ownership"])
            if not task["submissionAttempted"]:
                self._revalidate_inputs(ctx, task)
                with self.repository.transaction(ctx) as tx:
                    current = self._get(tx, ctx, task_id)
                    if self._owns(current, lease):
                        current.update(status="draft", lease=None, error=None, confirmation=None)
                        self._save(tx, current)
                    return {"task": public_task(current)}
            result = client.lookup(deepcopy(task["providerReceipt"]), local_task_id=task_id)
            if not isinstance(result, dict):
                raise TaskError("LOOKUP_UNCONFIRMED", "官方任务状态尚未确认。", 409)
            ref = merge_receipt(task["providerReceipt"], result.get("providerReceipt"))
            state = result.get("status")
            with self.repository.transaction(ctx) as tx:
                current = self._get(tx, ctx, task_id)
                if not self._owns(current, lease):
                    return {"task": public_task(current)}
                current.update(providerReceipt=merge_receipt(current["providerReceipt"], ref),
                               remoteStatus=state if state in {"queued", "running", "completed", "failed", "cancelled"} else "unknown")
                if state in {"queued", "running"}:
                    current.update(status=state, lease=None, error=None)
                elif state == "completed":
                    current.update(status="downloading", error=None)
                elif state == "failed":
                    upload_only = (result.get('failureStage') == 'reference_upload' and result.get('generationSubmitted') is False
                                   and not ref.get('taskId') and not ref.get('nodeId'))
                    current.update(status="failed", lease=None,
                        error=({"code":"REFERENCE_UPLOAD_FAILED", "message":"参考图上传未完成；已核实尚未调用收费生成。可以重新准备，原记录保留。",
                                "retryable":True, "details":{"generationSubmitted":False}}
                               if upload_only else {"code":"PROVIDER_TASK_FAILED", "message":"官方原任务失败，未自动重新生成。",
                                                    "retryable":False, "details":{}}))
                elif state == "cancelled":
                    current.update(status="cancelled", lease=None,
                                   cancellation={"localOnly": False, "remoteConfirmed": True, "refundConfirmed": False})
                else:
                    current.update(status="needs_attention", lease=None,
                                   error={"code": "ORIGINAL_TASK_UNCONFIRMED", "message": "暂未确认原任务状态，不会重新提交。",
                                          "retryable": False, "details": {}})
                self._save(tx, current)
                task = deepcopy(current)
                if state != "completed":
                    return {"task": public_task(task)}
            # Recheck the same identity immediately before receiving its media.
            self._identity(client, task["ownership"], ctx)
            downloaded = client.download(deepcopy(task["providerReceipt"]))
            self._revalidate_inputs(ctx, task)
            output_records = self._persist_outputs(ctx, task, downloaded)
            # Workflow also marks a racing old revision stale in its own atomic
            # commit. Recheck after that commit so the task explains the change.
            self._revalidate_inputs(ctx, task)
        except Exception as exc:
            return self._operation_failure(ctx, task_id, lease, exc)
        with self.repository.transaction(ctx) as tx:
            current = self._get(tx, ctx, task_id)
            if self._owns(current, lease):
                current.update(status="completed", lease=None, error=None, outputs=output_records,
                               review="pending", completedAt=self._now())
                self._save(tx, current)
            return {"task": public_task(current)}

    def _persist_outputs(self, ctx, task, downloaded):
        if not isinstance(downloaded, (list, tuple)) or len(downloaded) != task["prepared"]["count"]:
            raise TaskError("OUTPUT_INVALID", "返回文件数量与已确认任务不符，未标记完成。", 409)
        artifacts = []
        allowed_mimes = ({"application/json", "text/plain"} if task["recipe"] == "script_analysis"
                         else {"image/png", "image/jpeg", "image/webp"})
        for artifact in downloaded:
            if not isinstance(artifact, DownloadArtifact) or not isinstance(artifact.content, bytes) or not 0 < len(artifact.content) <= self.policy.max_output_bytes or artifact.mime not in allowed_mimes:
                raise TaskError("OUTPUT_INVALID", "返回文件格式或大小不符合任务约定。", 409)
            checksum = hashlib.sha256(artifact.content).hexdigest()
            if artifact.sha256 is not None and artifact.sha256 != checksum:
                raise TaskError("OUTPUT_INVALID", "返回文件校验失败，保留原任务供再次收取。", 409)
            artifacts.append((artifact, checksum))
        records = []
        for index, (artifact, checksum) in enumerate(artifacts):
            record = self.outputs.put(ctx, task_id=task["id"], ownership=deepcopy(task["ownership"]),
                                      index=index, content=artifact.content, mime=artifact.mime, sha256=checksum)
            blob_id = opaque(record.get("blobId"), "文件")
            stored = self.outputs.read(ctx, blob_id)
            if not isinstance(stored, bytes) or len(stored) != len(artifact.content) or hashlib.sha256(stored).hexdigest() != checksum:
                raise TaskError("OUTPUT_STORE_UNVERIFIED", "文件保存后的校验失败，任务尚未完成。", 409)
            entry = {"id": f"{task['id']}_output_{index + 1}", "blobId": blob_id,
                            "sha256": checksum, "mime": artifact.mime, "byteLength": len(stored),
                            "review": "pending"}
            for key in ("assetId", "revisionId"):
                if record.get(key) is not None:
                    entry[key] = opaque(record[key], key)
            records.append(entry)
        return records

    def cancel(self, ctx, task_id, expectedVersion):
        with self.repository.transaction(ctx) as tx:
            task = self._get(tx, ctx, task_id)
            self._expect(task, expectedVersion)
            if task["status"] == "completed":
                raise TaskError("TASK_ALREADY_COMPLETED", "文件已完成保存，请在资产审核中处理。", 409)
            if task["status"] != "cancelled":
                message = ("已停止本站处理；官方任务是否停止及退款均未确认。" if task["submissionAttempted"]
                           else "未提交的准备记录已取消，记录保留；尚未发起官方生成。")
                task.update(status="cancelled", lease=None, confirmation=None,
                            cancellation={"localOnly": True, "remoteConfirmed": False, "refundConfirmed": False},
                            error={"code": "LOCAL_PROCESSING_STOPPED", "message": message,
                                   "retryable": False, "details": {}})
                self._save(tx, task)
            return {"task": public_task(task)}

    def block_account(self, ctx, providerAccountId):
        """Called after removal/revocation. Files, ownership and receipts survive."""
        opaque(providerAccountId, "账号")
        affected = []
        with self.repository.transaction(ctx) as tx:
            for task in tx.list_tasks():
                if task.get("ownership", {}).get("tenantId") != tenant(ctx) or task["ownership"]["providerAccountId"] != providerAccountId or task["status"] in TERMINAL:
                    continue
                task.update(status="blocked_authorization", lease=None, confirmation=None,
                            error={"code": "ORIGINAL_AUTHORIZATION_REQUIRED", "message": "原账号授权已移除或失效。历史任务与文件保留，恢复同一身份授权后才能继续。",
                                   "retryable": False, "details": {}})
                self._save(tx, task)
                affected.append(task["id"])
        return affected

    def reconcile_after_restart(self, ctx):
        """Fences only expired work. Does not submit, prepare, or contact LibTV."""
        affected = []
        with self.repository.transaction(ctx) as tx:
            for task in tx.list_tasks():
                if task.get("ownership", {}).get("tenantId") != tenant(ctx) or task["status"] in TERMINAL:
                    continue
                lease = task.get("lease")
                if lease and parse_time(lease["expiresAt"]) > self.clock():
                    continue
                if not lease and task["status"] not in {"preparing", "submitting", "downloading"}:
                    continue
                if task["submissionAttempted"]:
                    task.update(status="needs_attention", error={"code": "INTERRUPTED_ORIGINAL_TASK",
                                "message": "处理曾中断，已保留原任务引用。仅查回原任务，不会重复生成。",
                                "retryable": False, "details": {}})
                elif task.get("prepared"):
                    task.update(status="draft", error=None)
                else:
                    task.update(status="needs_attention", error={"code": "PREPARATION_UNCONFIRMED",
                                "message": "准备步骤曾中断，请核对原记录。尚未确认生成提交。",
                                "retryable": False, "details": {}})
                task.update(lease=None, confirmation=None)
                self._save(tx, task)
                affected.append(task["id"])
        return affected

    def recover_pending(self, ctx, *, limit=50):
        """One bounded worker tick. The scheduler supplies each authenticated tenant."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise TaskError("VALIDATION_FAILED", "批量查回数量无效。", 422)
        self.reconcile_after_restart(ctx)
        with self.repository.transaction(ctx) as tx:
            candidates = [deepcopy(t) for t in tx.list_tasks()
                          if t.get("ownership", {}).get("tenantId") == tenant(ctx)
                          and t["submissionAttempted"] and t.get("providerReceipt")
                          and t["status"] in {"queued", "running", "downloading", "needs_attention"}][:limit]
        results = []
        for task in candidates:
            try:
                results.append(self.recover(ctx, task["id"], task["version"])["task"])
            except TaskError as exc:
                if exc.code not in {"TASK_BUSY", "VERSION_CONFLICT"}:
                    raise
        return results
