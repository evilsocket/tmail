"""Exercise the actual pinned upstream bridge against synthetic SMTP/IMAP mail."""
import json
import select
import subprocess


def exercise_mcp(root, host, password, check):
    config = root / 'himalaya.toml'
    config.write_text(f'''[accounts.tmail]
default = true
email = "alpha@tmail.internal"
imap.server = "imaps://{host}:1993"
imap.tls.cert = "{root}/ca.pem"
imap.sasl.plain.username = "alpha@tmail.internal"
imap.sasl.plain.password.raw = "{password}"
smtp.server = "smtps://{host}:1465"
smtp.tls.cert = "{root}/ca.pem"
smtp.sasl.plain.username = "alpha@tmail.internal"
smtp.sasl.plain.password.raw = "{password}"
''')
    log = open(root / 'mcp.log', 'w+')
    process = subprocess.Popen(['himalaya', '--config', str(config), '--account', 'tmail', 'mcp', '--allow-send'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)
    sequence = 0

    def rpc(method, params):
        nonlocal sequence
        sequence += 1
        process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': sequence, 'method': method, 'params': params}) + '\n')
        process.stdin.flush()
        assert select.select([process.stdout], [], [], 20)[0], f'MCP timed out: {method}'
        line = process.stdout.readline()
        if not line:
            log.flush()
            raise AssertionError((root / 'mcp.log').read_text())
        result = json.loads(line)
        assert 'error' not in result, result
        result = result['result']
        assert not result.get('isError'), result
        return result

    try:
        rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'tmail-test', 'version': '1'}})
        tools = {tool['name']: tool for tool in rpc('tools/list', {})['tools']}
        check(all(name in tools for name in ('envelope_list', 'message_read', 'message_reply', 'message_send')),
              'pinned MCP advertises read/send/reply tools')
        check(not any('delete' in name or 'move' in name or name == 'vacation_set' for name in tools),
              'destructive and unsupported MCP tools are absent')
        rpc('tools/call', {'name': 'envelope_list', 'arguments': {}})
        check(True, 'MCP can list mail through verified IMAP TLS')
        rpc('tools/call', {'name': 'message_read', 'arguments': {'id': '1'}})
        check(True, 'MCP can read a message')
        rpc('tools/call', {'name': 'message_reply', 'arguments': {'id': '1', 'body': 'Threaded synthetic MCP reply', 'send': True}})
        check(True, 'MCP can send a threaded reply through SMTP TLS')
        rpc('tools/call', {'name': 'message_send', 'arguments': {'message': [
            'From: alpha@tmail.internal\r\nTo: owner@tmail.internal\r\nSubject: MCP send test\r\n\r\nSynthetic MCP send.\r\n']}})
        check(True, 'MCP can send a new message')
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()
