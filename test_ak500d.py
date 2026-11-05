from ak500d import PACKET_CLOSE, build_packet


def test_packets() -> None:
    pkt = build_packet(temp_c=45.6, usage_pct=35, power_w=65, freq_mhz=4850, fahrenheit=False)
    assert pkt.hex() == "106801030d010208004100423666662312f23016", pkt.hex()
    assert len(pkt) == 20

    pkt_zero = build_packet(temp_c=0.0, usage_pct=0, power_w=0, freq_mhz=0, fahrenheit=False)
    assert pkt_zero.hex() == "106801030d010208000000000000000000008416", pkt_zero.hex()

    assert len(PACKET_CLOSE) == 20
    assert PACKET_CLOSE[0] == 0x10 and PACKET_CLOSE[-1] == 0x16
    assert (sum(PACKET_CLOSE[1:18]) & 0xFF) == PACKET_CLOSE[18]
    print("OK")


if __name__ == "__main__":
    test_packets()
