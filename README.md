# Zero_SIM by Amau_Zero

Full Flipper Zero simulator integration based on the `flippulator` engine.

## Screenshot

![Zero_SIM screenshot](assets/image.png)

## Clone (WSL first)

```bash
# 1) Open WSL terminal first
# 2) Create a folder where Zero_SIM will be installed
mkdir -p ~/zero_workspace
cd ~/zero_workspace

# 3) Clone and enter the repository
git clone https://github.com/Vaidx0/Zero_SIM.git
cd Zero_SIM
```

## Requirements

- Linux / WSL environment
- `make`
- `gcc`
- `libsdl2-dev:i386`
- `gcc-12-multilib` (or a compatible multilib GCC package)
- `libbsd-dev:i386`
- `nodejs` + `npm`

## Usage

```bash
npm install
npm start
```

This generates the simulator executable in `out_<app name>/<app name>`.

## Notes

- This project is based on the original `flippulator` architecture and adapted for `Zero_SIM`.
- It compiles Flipper apps for desktop simulation.

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