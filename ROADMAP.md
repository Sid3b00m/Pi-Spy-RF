# Pi-Spy-RF — build roadmap

## Phase 0-5
- [x] Web app, devices, spectrum, decode, WiFi/BT, auth, waterfall

## Phase 6 — Multi-SDR load balance
- [x] Exclusive scan vs decode roles (preempt extras to idle)
- [x] Auto-assign: RTL -> scan, HackRF -> decode
- [x] Workers bind only to their dedicated stick
- [x] Balance API + dashboard slots
- [ ] Later: two decode sticks in parallel

## Optional next
- [ ] Kismet adapter
- [ ] Real DSD/OP25 capture
