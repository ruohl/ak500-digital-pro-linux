package main

import (
	"encoding/hex"
	"testing"
)

func TestBuildPacket(t *testing.T) {
	var pkt [20]byte
	buildPacket(&pkt, 45.6, 35, 65, 4850, false)
	got := hex.EncodeToString(pkt[:])
	want := "106801030d010208004100423666662312f23016"
	if got != want {
		t.Fatalf("got %s, want %s", got, want)
	}

	buildPacket(&pkt, 0, 0, 0, 0, false)
	gotZero := hex.EncodeToString(pkt[:])
	wantZero := "106801030d010208000000000000000000008416"
	if gotZero != wantZero {
		t.Fatalf("got %s, want %s", gotZero, wantZero)
	}
}
