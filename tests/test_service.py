import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import service

class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"SENTINEL_TRACE_DIR":self.temp.name})
        self.env.start()
    async def asyncTearDown(self):
        self.env.stop();self.temp.cleanup()
    async def test_input_deny_never_calls_model(self):
        with patch.object(service,"judge",AsyncMock(return_value={})), \
             patch.object(service,"evaluate",AsyncMock(return_value={"decision":"deny"})), \
             patch.object(service,"generate",AsyncMock()) as model, \
             patch.object(service.Trace,"deliver",AsyncMock(return_value={"status":"accepted"})):
            result=await service.chat(None,{"messages":[{"role":"user","content":"test"}]})
            self.assertEqual(result["route"],"REFUSE");model.assert_not_called()
    async def test_unsafe_candidates_never_released(self):
        with patch.object(service,"judge",AsyncMock(return_value={})), \
             patch.object(service,"evaluate",AsyncMock(side_effect=[{"decision":"allow"},{"decision":"deny"},{"decision":"deny"}])), \
             patch.object(service,"generate",AsyncMock(return_value={"content":"WITHHOLD_THIS_CANDIDATE"})) as model, \
             patch.object(service.Trace,"deliver",AsyncMock(return_value={"status":"accepted"})):
            r=await service.chat(None,{"messages":[{"role":"user","content":"test"}]})
            self.assertEqual(r["route"],"WITHHELD");self.assertNotIn("WITHHOLD_THIS_CANDIDATE",r["response"])
            self.assertEqual(model.await_count,2)
    async def test_judge_failure_is_controlled_and_closed(self):
        with patch.object(service,"judge",AsyncMock(side_effect=TimeoutError())), \
             patch.object(service,"generate",AsyncMock()) as model, \
             patch.object(service.Trace,"deliver",AsyncMock(return_value={"status":"pending"})):
            r=await service.chat(None,{"messages":[{"role":"user","content":"test"}]})
            self.assertEqual(r["route"],"ERROR");model.assert_not_called()
            import json,pathlib
            lines=(pathlib.Path(self.temp.name)/(r["session_id"]+".jsonl")).read_text().splitlines()
            self.assertEqual(json.loads(lines[-1])["type"],"agent_end")

    async def test_steering_error_is_not_reported_as_applied(self):
        with patch.object(service,"judge",AsyncMock(return_value={})), \
             patch.object(service,"evaluate",AsyncMock(side_effect=[{"decision":"allow"},{"decision":"deny"}])), \
             patch.object(service,"generate",AsyncMock()) as model, \
             patch.object(service.Trace,"deliver",AsyncMock(return_value={"status":"accepted"})):
            r=await service.chat(None,{"messages":[{"role":"user","content":"test"}],"steering_mode":"on"})
            self.assertFalse(r["activation_steering_applied"])
            self.assertEqual(r["route"],"ERROR")
            model.assert_not_called()

    async def test_steering_usage_and_release_are_independent(self):
        with patch.object(service,"judge",AsyncMock(return_value={})), \
             patch.object(service,"evaluate",AsyncMock(side_effect=[{"decision":"allow"},{"decision":"allow"},{"decision":"deny"},{"decision":"deny"}])), \
             patch.object(service,"generate",AsyncMock(return_value={"content":"DO_NOT_RELEASE","activation_steering_applied":True,"steering":{"alpha":.08}})), \
             patch.object(service.Trace,"deliver",AsyncMock(return_value={"status":"accepted"})):
            r=await service.chat(None,{"messages":[{"role":"user","content":"test"}],"steering_mode":"on"})
            self.assertTrue(r["activation_steering_applied"])
            self.assertEqual(r["route"],"WITHHELD")
            self.assertNotIn("DO_NOT_RELEASE",r["response"])

    async def test_requested_steering_requires_worker_confirmation(self):
        with patch.object(service,"judge",AsyncMock(return_value={})), \
             patch.object(service,"evaluate",AsyncMock(return_value={"decision":"allow"})), \
             patch.object(service,"generate",AsyncMock(return_value={"content":"UNCONFIRMED","activation_steering_applied":False})), \
             patch.object(service.Trace,"deliver",AsyncMock(return_value={"status":"accepted"})):
            r=await service.chat(None,{"messages":[{"role":"user","content":"test"}],"steering_mode":"on"})
            self.assertEqual(r["route"],"ERROR")
            self.assertNotIn("UNCONFIRMED",r["response"])
            self.assertFalse(r["activation_steering_applied"])

    async def test_paired_input_is_reused_but_output_is_judged(self):
        fixed={"prohibited":0.01,"missing_context":0.02,"safe_reframing":0.03}
        with patch.object(service,"judge",AsyncMock(return_value={"harmful":0.01})) as judge, \
             patch.object(service,"evaluate",AsyncMock(return_value={"decision":"allow"})), \
             patch.object(service,"generate",AsyncMock(return_value={"content":"safe answer"})), \
             patch.object(service.Trace,"deliver",AsyncMock(return_value={"status":"accepted"})):
            r=await service.chat(None,{"messages":[{"role":"user","content":"test"}]},fixed_input_judgment=fixed)
            self.assertEqual(r["input_judgment"],fixed)
            self.assertTrue(r["input_judgment_reused"])
            judge.assert_awaited_once()
            self.assertEqual(judge.await_args.args[2],"output")

if __name__=="__main__":unittest.main()
