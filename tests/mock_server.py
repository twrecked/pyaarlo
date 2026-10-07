from aiohttp import web
import asyncio
import json

class ArloMockServer:
    def __init__(self, port=8080):
        self.port = port
        self.app = web.Application()
        self.app['event_queue'] = asyncio.Queue()
        self.app.router.add_get('/hmsweb/client/subscribe', self.sse_handler)
        self.app.router.add_get('/hmsweb/users/session/v3', self.session_v3_handler)
        self.app.router.add_get('/hmsweb/v2/users/devices', self.devices_handler)
        self.app.router.add_post('/hmsweb/users/library', self.library_handler)
        self.runner = None

    async def session_v3_handler(self, request):
        return web.json_response({
            "meta": {"code": 200},
            "data": {
                "userId": "user-mock-sse",
                "authenticated": True
            }
        })

    async def library_handler(self, request):
        return web.json_response({
            "meta": {"code": 200},
            "data": []
        })

    async def devices_handler(self, request):
        return web.json_response({
            "meta": {"code": 200},
            "data": []
        })

    async def sse_handler(self, request):
        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
            },
        )
        await response.prepare(request)
        
        # Initial connected event
        await response.write(b"data: {\"status\": \"connected\"}\n\n")
        
        try:
            while True:
                event = await self.app['event_queue'].get()
                if event is None:
                    break
                await response.write(f"data: {json.dumps(event)}\n\n".encode('utf-8'))
        finally:
            return response

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, 'localhost', self.port)
        await site.start()
        print(f"Mock Arlo Server started at http://localhost:{self.port}")

    async def stop(self):
        if self.runner:
            # Signal all waiting SSE handlers to stop
            # (In a real scenario with multiple clients we'd need more logic)
            await self.app['event_queue'].put(None)
            await self.runner.cleanup()

    async def push_event(self, event):
        await self.app['event_queue'].put(event)
