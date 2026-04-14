# Zero_Sim Toolkit by Amau_Zero

Website: [amauzero.info](https://amauzero.info)

A clean helper workflow for Zero_Sim with:
- dependency bootstrap
- quiet app build (logs shown only on error)
- one-command simulator launch
- rich terminal UI

## Requirements

- Windows with WSL installed
- Python 3 available (`python` or `py -3` on Windows)
- Git installed
- Node.js + npm installed

## Screenshot

![Zero_Sim screenshot](assets/image.png)

## Clone

```bash
git clone https://github.com/Vaidx0/Zero_SIM.git
cd Zero_SIM
```

## First Create an App Folder

Before building, create an app folder in the repository root and add an `application.fam` file.

Example:

```bash
mkdir my_image_viewer
```

## Setup Zero_Sim

Run from the repository folder (where `simulator.py` is located):

```bash
python simulator.py deps
```

If `python` is not available on your machine, use:

```bash
py -3 simulator.py deps
```

This command checks and installs missing dependencies automatically.

## Build an App

```bash
python simulator.py build my_image_viewer
```

## Run the Simulator

```bash
python simulator.py run my_image_viewer
```

## Interactive Mode

```bash
python simulator.py
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

<table>
  <tr>
    <td width="220" align="center">
      <img src="https://camo.githubusercontent.com/6eef2f1c39354d8ad9e18912bcd4f86e000cfc5eafd668d3efaa5e0c666e46de/68747470733a2f2f7777772e616d61757a65726f2e696e666f2f6173736574732f636172706c61792d65737033322d312d43323170316751302e706e67" alt="Amau_Zero" width="180" />
    </td>
    <td align="left" valign="middle">
      <strong>Amau_Zero</strong><br />
      <a href="https://amauzero.info">https://amauzero.info</a>
    </td>
  </tr>
</table>
