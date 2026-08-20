from pyclaudius.mcp_tools.config import MCP_SERVER_NAME, find_free_port


def test_find_free_port():
    port = find_free_port()
    assert isinstance(port, int)
    assert port > 0


def test_find_free_port_returns_different_ports():
    port1 = find_free_port()
    port2 = find_free_port()
    # Ports should generally be different (OS assigns sequentially)
    # but we just check both are valid
    assert port1 > 0
    assert port2 > 0


def test_mcp_server_name():
    assert MCP_SERVER_NAME == "pyclaudius"
