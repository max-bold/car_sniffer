# Runtime behavior and limits

## Bridge and capture

Power/reset starts with bridge off and both controllers silent/listen-only, without ACK or active error flags. Manual bitrate Apply is an explicit user confirmation; Auto confirms only after three valid received frames at a candidate speed. Both sides must be confirmed at the same configured rate to enable bridge. Changing a bitrate stops the bridge and reports an event before reconfiguration. Auto never runs covertly on a live bridge.

Forwarding is full-frame store-and-forward. A successfully received frame may have been locally ACKed before its forwarding attempt; this ACK does not prove delivery on the opposite segment. Invalid/error frames are never forwarded. Identical real frames from opposite sides remain distinct. Each destination has a 64-frame bounded FIFO, independent from USB telemetry and the opposite direction. CAN filter banks 0/14 accept all, CAN2 starts at bank14, and CAN1 clock stays enabled for CAN2.

One mailbox is used per destination at a time for deterministic order and unambiguous completion attribution. Enqueue order is maintained by this firmware; external bus arbitration can still delay every transmission. NART is enabled: one hardware attempt, zero software retries. Lost arbitration may result in failure of the single attempt; it is not labeled as a faulty bus. This conservative first implementation sacrifices peak throughput to bound stale deliveries. Delivery deadline is 20 ms including queue wait. Expired TX is aborted; overflow/expiry/drop events and counters are visible. A failed destination cannot block the other side or USB. Reconfiguration and bus-off discard affected queued/inflight frames. No stale queue is replayed after recovery.

Automatic bus-off recovery is disabled in hardware. Main-loop recovery tries a controlled reinitialization at most once per second, at most three times per side until manual bitrate Apply resets the budget. Recovery attempts and state transitions are events. A reinitialization request is not proof of electrical recovery; ESR and new traffic determine observed state. Persistent failure requires bench investigation and explicit reconfiguration, never an endless restart loop.

Capture controls collection of CAN RX/TX rows and averaged ADC results. Diagnostics/control continue when capture is stopped. Forwarding never consults capture or USB state. Windows filters and Clear results never affect MCU forwarding or acquisition. Physical segments stay separate when bridge is off; to passively observe a shared bus, connect one side without cutting the bus.

## Auto

Candidate order 125,250,500,1000,100,83.333 kbit/s, 300 ms each in silent mode. Three valid frames confirm a rate; otherwise returns unknown after six attempts. A quiet bus and unsupported bitrate are not guessed. A lone transmitter on an isolated segment may lack ACK and fail to provide successfully received frames; supply a second properly configured node or select the known rate manually. Silent Auto never adds ACK/probe traffic.

## Error observation

LEC is polled/cleared as the last observed error. It is not an exhaustive physical error-frame trace. TEC/REC, warning/passive/bus-off are sampled, timestamped and displayed. CRC errors produce controller events without invented damaged-frame ID/DATA. RX_ACK is always N/A. A forwarded successful mailbox gives TX_ACK=1; ACK LEC is controller-level, so failure rows remain N/A instead of claiming frame-specific ACK=0. Only successful hardware RX gives CRC_OK=1. Counters cannot uniquely identify a guilty ECU.

## Memory and desktop

MCU ISR RX rings: 128 per side; forwarding queues: 64 per direction; ADC: double 16-scan DMA buffer plus four copied blocks; telemetry: 256 records of up to 128 bytes; command response queue:16. Interrupts copy bounded data only; main performs calibration and packet batching. CAN IRQ priority2, ADC3, USB6; TIM5 wrap0. USB loss counts include telemetry intentionally discarded while disconnected. USB command-ring overruns produce USB loss events. DMA block loss produces an event and resets averaging windows; timestamp gaps identify missing windows. No CCM data is used by DMA.

Desktop worker performs serial I/O, framing and demo generation outside the Qt thread. Its packet inbox holds 4096 envelopes; overflow removes the oldest packet and increments a visible host loss count. GUI drains batches on a nominal 40 ms timer; under heavy load repaint frequency may fall below25 Hz. This is independent of the 100 Hz/channel hardware acquisition rate. Raw calibration buffering is limited to16000 selected-channel samples. CAN table storage is limited to20000 rows per side; old-row eviction is counted visibly. Each analog trace retains6000 points (60 s), with evictions counted. Qt model/view and one curve per channel avoid per-frame widgets. Both tables have independent ID/IDE/RTR/event filters and autoscroll.

There is no capture-file save/load/export. Calibration JSON is not a capture recording. There is no arbitrary CAN injection; only a fixed internal silent-loopback self-test. The current bench cannot validate high-load real CAN, arbitration/ACK/bus-off behavior or physical ADC accuracy. These require a transceiver-equipped bench.

Right-click either CAN table header to toggle column visibility for that table. Menu entries follow the displayed column order; at least one column stays visible. Visibility survives filtering and Clear results within the current application session, and resets when the application restarts. Hidden columns retain their data and TX updates.

## Fixed analog circuit

The only analog range is0..15 V, using a permanent47k/10k divider with100k bias to VREF. The main app has channel enable controls and no DIV controls; legacy saved range preferences are ignored. PD8..PD15 are unused, and the ADC scan order remains PC0,PC1,PC2,PA1..PA5. Calibration is GND then approximately10 V, eight profiles. Old CAL1 profiles are preserved but not applied; new CAL2 calibration is required. The removed shunt zeners and absent Schottky diodes mean input fault protection remains unverified.
