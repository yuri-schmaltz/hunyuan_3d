"""Same as hy3dgen.api.server but with the worker disabled (idle loop)."""
import sys
sys.path.insert(0, "/workspace/my-hunyuan-3D/.worktrees/feature-ui")

import hy3dgen.api.manager as _mgr
import asyncio

async def _idle(self):
    while True:
        await asyncio.sleep(3600)

_mgr.PriorityRequestManager._process_queue = _idle

from hy3dgen.api.server import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
