# Radio Scanner SDR

A deployable radio scanner for Raspberry Pi or Ubuntu laptops, integrating WiFi surveillance detection (via Chasing-Your-Tail-NG) with broad-spectrum SDR scanning (120-950 MHz). Supports RTL-SDR v3/v4 and HackRF One.

## Features
- **WiFi Surveillance Detection**: Uses Kismet and CYT-NG for tracking devices and probes.
- **Spectrum Scanning**: Detects signals in 120-950 MHz range.
- **Digital Decoding**: POCSAG, FLEX paging.
- **Analog Demodulation**: FM/AM voice (e.g., broadcast, aircraft).
- **NOAA Weather Radio**: SAME alerts and voice on 162 MHz.
- **NOAA Satellite APT**: Decodes weather images on 137 MHz with Doppler slant correction.
- **Logging**: Outputs to `scanner.log` and console.

## Requirements
- Raspberry Pi (with Raspbian) or Ubuntu laptop.
- RTL-SDR v3/v4 or HackRF One hardware.
- WiFi adapter supporting monitor mode (e.g., wlan1).
- Root access for SDR and Kismet.

## Installation
1. Clone this repo:
    git clone https://github.com/yourusername/radio-scanner-sdr.git
    cd radio-scanner-sdr
2. Make the script executable:
                                    
3. Run installation (use `--hackrf` for HackRF):
- This installs dependencies, clones CYT-NG, sets up configs, and blacklists conflicting modules.
- For HackRF: `./setup_scanner.sh --install --hackrf`

## Usage
1. Run the scanner (defaults to RTL-SDR):

- For HackRF: `./setup_scanner.sh --hackrf` (installs HackRF deps if needed and runs).

2. Monitor output:
- Logs in `~/cytng_scanner/scanner.log`.
- Decoded images/WAVs saved in the working directory.
- Press Ctrl+C to stop.

3. Customization:
- Edit variables in `setup_scanner.sh` (e.g., frequencies, gain).
- For longer satellite recordings: Modify `record_duration` in the Python section.
- Kismet DB path: Update `KISMET_DB_PATH` or `config.json`.

## Troubleshooting
- **SDR Not Detected**: Ensure hardware is plugged in. Run `rtl_test` (RTL-SDR) or `hackrf_info` (HackRF).
- **Permissions**: Run with sudo if USB access issues.
- **Kismet Errors**: Ensure wlan1 is in monitor mode (use `iwconfig` to check).
- **HackRF Limitations**: APT decoding is partial; consider integrating GNU Radio for full support.
- **Dependencies**: If pip fails, try `pip3 install --user ...`.
- **No Signals**: Check antenna, gain (increase if needed), and location.
                                                                                        
                                                                                        
    ./setup_scanner.sh --run
                                                                                        
                                                                                        
## Credits
- Based on [Chasing-Your-Tail-NG](https://github.com/ArgeliusLabs/Chasing-Your-Tail-NG).
- NOAA APT decoding via [noaa-apt](https://github.com/martinber/noaa-apt).
- Contributions welcome!
