# Zero_Sim Toolkit by Amau_Zero

Website: [amauzero.info](https://amauzero.info)

A clean helper workflow for Zero_Sim with:
- dependency bootstrap
- quiet app build (logs shown only on error)
- one-command simulator launch
- rich terminal UI

## Requirements

- Windows with WSL installed
- Python 3 installed in WSL
- Git installed in WSL
- Node.js + npm installed in WSL

## Screenshot

![Zero_Sim screenshot](assets/image.png)

## Clone

```bash
git clone https://github.com/Vaidx0/Zero_SIM.git
cd Zero_SIM
```

## Setup Zero_Sim

```bash
cd ~/Zero_Sim
python3 simulator.py deps
```

This command checks and installs missing dependencies automatically.

## Build an App

```bash
cd ~/Zero_Sim
python3 simulator.py build my_image_viewer
```

## Run the Simulator

```bash
cd ~/Zero_Sim
python3 simulator.py run my_image_viewer
```

## Interactive Mode

```bash
cd ~/Zero_Sim
python3 simulator.py
```

## Keyboard Controls (Zero_Sim)

- Up: `Arrow Up`
- Down: `Arrow Down`
- Left: `Arrow Left`
- Right: `Arrow Right`
- OK: `Z`
- Back: `X`

## Notes

- Build output is intentionally hidden unless a build step fails.
- If dependency installation asks for sudo, enter your WSL password.
- ALSA warnings can appear on machines without an audio device and are usually harmless.

## Author

**Amau_Zero**  
Website: [amauzero.info](https://amauzero.info)
