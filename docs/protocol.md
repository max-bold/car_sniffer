# Binary protocol v1

Implementations: `firmware/include/protocol.h`, `firmware/src/protocol.c`, `desktop/protocol.py`. All multi-byte integers are **little endian**. Floats are IEEE754 binary32. Packed records have no padding. Timestamps are uint64 microseconds from the MCU monotonic TIM5 clock, scoped by boot ID. CAN RX timestamps are ISR processing time, **not SOF**.

## Envelope

| Offset | Field | Type |
|---:|---|---|
| 0 | ASCII `CS` magic | 2 bytes |
| 2 | Version=1 | uint8 |
| 3 | Kind 1..9 | uint8 |
| 4 | Payload size, maximum 1024 | uint16 |
| 6 | Sequence | uint32 |
| 10 | Payload | size bytes |
| 10+size | CRC32 | uint32 |

CRC is standard reflected CRC-32/ISO-HDLC, polynomial 0xEDB88320, initial/final XOR 0xFFFFFFFF, covering header and payload. `123456789` -> 0xCBF43926. This is the **USB transport** CRC, unrelated to CAN CRC. Sequence counts transmitted envelopes in each direction, modulo 2^32. Dropped MCU telemetry is counted separately because it may be discarded before packetization. A host reconnect resets parser sequence history; a new boot ID starts a new time axis and sequence session. Parser accepts fragments, concatenation, noise and oversized-length rejection. A damaged plausible length may delay resynchronization until its bounded candidate packet can be checked (maximum 1038 bytes); there is no unbounded allocation.

Kinds: COMMAND=1, RESPONSE=2, STATUS=3, CAN_RX=4, TX_STATUS=5, EVENT=6, ADC=7, RAW=8, AUTO=9. Payloads for kinds 3..9 are homogeneous concatenated packed records; COMMAND and RESPONSE carry exactly one operation.

## Commands and response

Command prefix `request_id:uint32, command:uint8`. The table lists remaining argument bytes. Invalid length/value returns code 1, state conflict code 2, peripheral failure code 3. A malformed envelope is discarded without executing commands. GUI detects missing responses after 3 s.

| Command | Number | Arguments |
|---|---:|---|
| Status | 1 | none |
| CAN configuration | 2 | side:u8, bitrate:u32 (0=Auto; 83333,100000,125000,250000,500000,1000000) |
| Bridge | 3 | enable:u8, 0/1 |
| Capture | 4 | enable:u8, 0/1 |
| Channel | 5 | channel:u8 0..7, enable:u8, range:u8 0=3.3V,1=15V |
| Profile | 6 | channel:u8, range:u8, version:u32, count:u8 2..32, then count * (raw:u16,volts:f32) |
| Raw session | 7 | channel:u8, duration_ms:u16 0..10000, zero cancels |
| Clear counters | 8 | none; leaves capture/bridge/GUI results alone |
| Internal loopback self-test | 9 | side:u8; bridge and Auto must be off; sends fixed ID 321/data 43 53 01 02 03 04 05 06 in **silent loopback**, restores silent mode |

Response: `request_id:u32, command:u8, result:u8, applied_boundary_us:u64` (14 bytes). Profile update, capture and range boundaries exclude queued pre-command ADC samples; boundary is application time, not host receipt time. Capture stop leaves packets collected before the boundary in the telemetry queue, followed by EV_CAPTURE; GUI displays these already collected results. Clear results is local and sends no MCU reset/counter command.

## Record layouts

Notation follows Python `struct` with implicit little-endian prefix `<`.

| Kind | Layout | Fields |
|---|---|---|
| CAN_RX | `QII5B8s`, 29 bytes | timestamp, frame_id, CAN ID, side, IDE, RTR, original DLC, CRC_OK, data[8] |
| TX_STATUS | `QIBBb`, 15 bytes | timestamp, original frame_id, destination side, state, signed TX_ACK |
| EVENT | `QBBIII`, 22 bytes | timestamp, side, code, detail, TEC, REC |
| ADC | `QBBHfffI`, 28 bytes | window start, channel, range, quality, raw mean, raw population std, volts, profile version |
| RAW | `QBBH`, 12 bytes | scan trigger time, channel, range, raw ADC |
| AUTO | `QBBI`, 14 bytes | timestamp, side, stage, bitrate |
| STATUS | `QIII12sBBBBII16I`, 108 bytes | timestamp, boot ID, telemetry lost records, capture generation, UID[12], bridge, capture, CAN state A, CAN state B, rate A, rate B, 8 counters A then 8 B |

Side A=0, B=1, device-wide events=255. CAN ID respects IDE, RTR carries no data (eight transport padding bytes are zero). DLC retains the hardware field, display uses at most eight data bytes. CRC_OK=1 means bxCAN accepted the frame. ACK_RX is always N/A because receive mailboxes do not expose it.

TX states: 0 pending, 1 sent, 2 failed, 3 expired, 4 dropped. TX_ACK: -1 N/A/unattributable, 0 attributable ACK failure (reserved; current hardware backend reports ACK errors at controller level), 1 successful own transmission in normal mode, 2 pending. Successful forwarding updates the source RX row, never creates an invented external RX. Loopback is explicitly marked as a test event.

CAN state byte: low two bits 0=silent,1=normal,2=silent-loopback; bits 4/5/6 are bxCAN error warning/passive/bus-off. Counters per side: RX, successful forwarded TX, observed LEC errors, RX loss, TX failed/dropped, expired, current TEC, current REC. Counter wrap is modulo 2^32. A sequence gap counts missing envelopes, not missing CAN frames.

Event codes: 1 LEC(detail 1 stuff,2 form,3 ACK,4 recessive bit,5 dominant bit,6 CRC); 2 state(detail ESR low 3 bits); 3 RX loss; 4 TX queue overflow(detail original frame_id); 5 expiry(frame_id); 6 USB loss(count); 7 recovery(attempt 1..3,0 restored); 8 bridge stopped; 9 range(channel<<8|range); 10 DMA loss(block count); 11 capture(enable); 12 loopback(0 started,1 received); 13 RX records discarded by reconfiguration(count). Controller-level LEC is not falsely attached to a specific frame.

ADC quality bitmask: 1 uncalibrated,2 clipping on any raw sample,4 settling,8 outside selected voltage range,16 outside table,32 DMA loss (reserved for individual point tagging; current implementation reports dropped DMA blocks as events and breaks windows). Invalid settling/outside-table values carry NaN. Nominal voltage uses 3.3/4095 * raw * (1 or 5), never 15/3.3.

Auto stage 0 trying,1 found,2 not determined. Raw is one selected channel at 1600 samples/s for at most 10 s. Normal eight-channel scans and CAN operation continue.

## Capacity

Two 1 Mbit/s Classic CAN buses carrying minimum-size standard frames can approach 2*(1e6/47)=42,553 RX/s before stuffing. At 29 bytes/RX this alone is approximately 1.23 MB/s; two 15-byte TX statuses per forwarded frame add roughly 1.28 MB/s. USB FS bulk practical upper bound is about 1.216 MB/s, below this telemetry demand. Full-fidelity capture of both maximally loaded buses is therefore not guaranteed. Batching removes envelope overhead but cannot solve the bandwidth bound. Eight ADC streams need 22,400 payload bytes/s; raw adds 19,200 bytes/s. Forwarding continues independently when telemetry is dropped.
