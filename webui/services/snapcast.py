"""Snapcast JSON-RPC client"""

import asyncio
import json
from typing import Any


class SnapcastClient:
    def __init__(self, host: str = 'localhost', port: int = 1705):
        self.host = host
        self.port = port
        self._request_id = 0

    async def _call(self, method: str, params: dict | None = None) -> dict:
        """Make a JSON-RPC call to Snapcast server"""
        self._request_id += 1

        request = {
            'id': self._request_id,
            'jsonrpc': '2.0',
            'method': method,
        }
        if params:
            request['params'] = params

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=5.0
            )

            # Send request
            writer.write(json.dumps(request).encode() + b'\r\n')
            await writer.drain()

            # Read response
            response_data = await asyncio.wait_for(
                reader.readline(),
                timeout=5.0
            )

            writer.close()
            await writer.wait_closed()

            response = json.loads(response_data.decode())

            if 'error' in response:
                raise Exception(response['error'].get('message', 'Unknown error'))

            return response.get('result', {})

        except asyncio.TimeoutError:
            raise Exception('Connection timeout')
        except ConnectionRefusedError:
            raise Exception('Connection refused - is snapserver running?')
        except Exception as e:
            raise Exception(f'Snapcast error: {str(e)}')

    async def get_status(self) -> dict:
        """Get server status including groups, clients, and streams"""
        result = await self._call('Server.GetStatus')
        server = result.get('server', {})

        # Simplify the response
        streams = []
        for stream in server.get('streams', []):
            streams.append({
                'id': stream.get('id'),
                'status': stream.get('status', 'unknown'),
                'uri': stream.get('uri', {}).get('raw', ''),
            })

        groups = []
        for group in server.get('groups', []):
            clients = []
            for client in group.get('clients', []):
                clients.append({
                    'id': client.get('id'),
                    'name': client.get('config', {}).get('name', ''),
                    'connected': client.get('connected', False),
                    'volume': client.get('config', {}).get('volume', {}).get('percent', 100),
                })

            groups.append({
                'id': group.get('id'),
                'name': group.get('name', ''),
                'stream_id': group.get('stream_id'),
                'muted': group.get('muted', False),
                'clients': clients,
            })

        return {
            'streams': streams,
            'groups': groups,
        }

    async def set_group_stream(self, group_id: str, stream_id: str) -> bool:
        """Set the stream for a group"""
        await self._call('Group.SetStream', {
            'id': group_id,
            'stream_id': stream_id,
        })
        return True

    async def set_group_mute(self, group_id: str, mute: bool) -> bool:
        """Mute/unmute a group"""
        await self._call('Group.SetMute', {
            'id': group_id,
            'mute': mute,
        })
        return True

    async def set_client_volume(self, client_id: str, volume: int) -> bool:
        """Set volume for a client (0-100)"""
        await self._call('Client.SetVolume', {
            'id': client_id,
            'volume': {'percent': volume, 'muted': False},
        })
        return True

    async def set_client_name(self, client_id: str, name: str) -> bool:
        """Set name for a client"""
        await self._call('Client.SetName', {
            'id': client_id,
            'name': name,
        })
        return True

    async def set_group_name(self, group_id: str, name: str) -> bool:
        """Set name for a group"""
        await self._call('Group.SetName', {
            'id': group_id,
            'name': name,
        })
        return True
