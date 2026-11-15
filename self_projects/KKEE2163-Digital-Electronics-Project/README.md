# KKEE2163 Digital Electronics Project — Accelerometer Gesture Game

An FPGA-based gesture-recognition game built on the **Nexys A7-100T** (Artix-7). The player performs three physical motions — **Throw**, **Pull**, and **Turn** — detected by the on-board **ADXL362 accelerometer** via SPI. The game displays animated character sprites on a VGA monitor, plays PWM audio through each phase, shows live score and countdown on the 7-segment display, and maps raw accelerometer data to the 15 on-board LEDs.

---

## Table of Contents

1. [Hardware Requirements](#hardware-requirements)
2. [Project Structure](#project-structure)
3. [System Architecture](#system-architecture)
4. [Module Reference](#module-reference)
   - [master_game_top](#master_game_top)
   - [iclk_gen](#iclk_gen)
   - [spi_master](#spi_master)
   - [action_fsm](#action_fsm)
   - [seg7_control](#seg7_control)
   - [VGA_TEST](#vga_test)
   - [VGA](#vga)
   - [IMAGE_ROM](#image_rom)
   - [UI_TEXT_ENGINE](#ui_text_engine)
   - [main_game_audio_processor](#main_game_audio_processor)
   - [note_generator](#note_generator)
   - [scoring_design (unused legacy)](#scoring_design)
   - [top (unused legacy)](#top)
5. [Game Flow](#game-flow)
6. [Pin Mapping (Constraints)](#pin-mapping)
7. [Sprite Assets](#sprite-assets)
8. [Building and Programming](#building-and-programming)

---

## Hardware Requirements

| Component | Detail |
|-----------|--------|
| FPGA Board | Digilent Nexys A7-100T (Artix-7 XC7A100T) |
| Accelerometer | ADXL362 (on-board, SPI interface) |
| Display | VGA monitor (640×480 @ 60 Hz) |
| Audio | On-board PWM audio amplifier (Pin A11 / D12) |
| Controls | Switch SW0 (J15) — start/reset; CPU Reset button (C12) |
| Indicators | 15 LEDs (raw accel data), 8-digit 7-segment display |

---

## Project Structure

```
KKEE2163_Digital_Electronics_Project/
├── KKEE2163_Digital_Electronics_Project.xpr    # Vivado project file
├── KKEE2163_Digital_Electronics_Project.srcs/
│   ├── sources_1/new/                          # All Verilog source files
│   │   ├── master_game_top.v                   # Top-level module (active)
│   │   ├── action_fsm.v                        # Game logic FSM & scoring
│   │   ├── spi_master.v                        # ADXL362 SPI driver
│   │   ├── iclk_gen.v                          # 100 MHz → 4 MHz clock divider
│   │   ├── seg7_control.v                      # 7-segment display controller
│   │   ├── VGA_TEST.v                          # VGA top-level (sprites + UI + state machine)
│   │   ├── VGA.v                               # VGA timing generator (640×480 @ 60 Hz)
│   │   ├── IMAGE_ROM.v                         # Parameterized BRAM image ROM (160×120, 12-bit)
│   │   ├── UI_TEXT_ENGINE.v                     # Bitmap font renderer for menus & results
│   │   ├── main_game_audio_processor.v          # PWM audio engine with melody sequencer
│   │   ├── scoring_design.v                    # Legacy scoring module (not instantiated)
│   │   └── top.v                               # Legacy top module (not instantiated)
│   └── constrs_1/new/
│       └── ucf.xdc                             # Pin constraints for Nexys A7
├── *.hex                                       # 9 sprite animation frames (160×120 @ 12-bit color)
└── .gitignore
```

---

## System Architecture

```
                         ┌─────────────────────────────────────────────┐
                         │            master_game_top                  │
                         │                                             │
  CLK100MHZ ────────────►│  ┌───────────┐    ┌──────────────┐         │
                         │  │ iclk_gen  │───►│  spi_master  │──► SPI  │──► ADXL362
                         │  │(100→4MHz) │    │  (ADXL362)   │   Pins  │
                         │  └───────────┘    └──────┬───────┘         │
                         │                          │ acl_data[14:0]  │
                         │            ┌─────────────┼─────────────┐   │
                         │            ▼             ▼             ▼   │
                         │     ┌────────────┐ ┌──────────┐  ┌──────┐ │
  SW0 (J15) ────────────►│────►│ action_fsm │ │ VGA_TEST │  │ LEDs │ │
                         │     │ (scoring)  │ │ (display)│  │[14:0]│ │
                         │     └─────┬──────┘ └────┬─────┘  └──────┘ │
                         │           │             │                  │
                         │    score, timer,   VGA R/G/B,              │
                         │    fsm_state       H/V Sync                │
                         │           │             │                  │
                         │     ┌─────▼──────┐     │                  │
                         │     │seg7_control│     │                  │
                         │     │(7-seg disp)│     │                  │
                         │     └────────────┘     │                  │
                         │                        │                  │
                         │   ┌────────────────────┘                  │
                         │   │  FSM state (mapped)                   │
                         │   ▼                                       │
                         │  ┌──────────────────────────┐             │
                         │  │main_game_audio_processor │──► AUD_PWM  │
                         │  │  (PWM melody + SFX)      │──► AUD_SD   │
                         │  └──────────────────────────┘             │
                         └─────────────────────────────────────────────┘
```

### Data Flow Summary

1. **Clock**: The board's 100 MHz clock feeds everything. `iclk_gen` derives a 4 MHz clock for the SPI master.
2. **Accelerometer**: `spi_master` initializes the ADXL362 into measurement mode, then continuously reads X/Y/Z registers at ~100 Hz. Each axis is packed into 5 bits (1 sign + 4 magnitude) → 15-bit `acl_data` bus.
3. **Game Logic**: `action_fsm` consumes `acl_data` and drives a 6-state FSM (IDLE → INIT → THROW → PULL → TURN → DONE). It outputs `final_marks` (8-bit score), `timer_sec` (4-bit countdown), and `state_out` (3-bit state).
4. **Display**: `VGA_TEST` runs its own parallel state machine for VGA visuals. It instantiates 9 `IMAGE_ROM` instances (3 frames × 3 motions), the `VGA` timing generator, and `UI_TEXT_ENGINE` for text overlays.
5. **Audio**: `main_game_audio_processor` receives the FSM state (mapped from action_fsm's numbering) and plays different melodies per phase using clock-divider square-wave generators.
6. **7-Segment**: `seg7_control` multiplexes the score (AN0–AN1) and countdown timer (AN6–AN7) across the 8-digit display at ~125 Hz refresh.
7. **LEDs**: The raw 15-bit accelerometer data is directly assigned to LED[14:0] for real-time debugging.

---

## Module Reference

### `master_game_top`
**File**: `master_game_top.v`  
**Role**: Top-level module. Instantiates all subsystems, wires them together, and maps FSM state numbers from `action_fsm` encoding to `main_game_audio_processor` encoding.

| Port | Direction | Width | Description |
|------|-----------|-------|-------------|
| `CLK100MHZ` | input | 1 | 100 MHz system clock |
| `reset_btn` | input | 1 | CPU reset (active-low) |
| `sw` | input | 1 | Switch 0 — game start/reset |
| `ACL_MISO` | input | 1 | SPI MISO from ADXL362 |
| `ACL_MOSI` | output | 1 | SPI MOSI to ADXL362 |
| `ACL_SCLK` | output | 1 | SPI clock to ADXL362 |
| `ACL_CSN` | output | 1 | SPI chip select (active-low) |
| `LED[14:0]` | output | 15 | Raw accelerometer data display |
| `SEG[6:0]` | output | 7 | 7-segment cathodes |
| `DP` | output | 1 | Decimal point |
| `AN[7:0]` | output | 8 | 7-segment anodes |
| `vga_r/g/b[3:0]` | output | 4 each | VGA color channels (12-bit) |
| `vga_hsync/vsync` | output | 1 each | VGA sync signals |
| `AUD_PWM` | output | 1 | Audio PWM output |
| `AUD_SD` | output | 1 | Audio amplifier shutdown (active-low, always held high) |

**State mapping** (action_fsm → audio engine):
| action_fsm | Audio State | Meaning |
|------------|-------------|---------|
| 0 (IDLE) | 1 (HOLD) | Silence |
| 1 (INIT) | 4 (COUNTDOWN) | Beep ticks |
| 2 (THROW) | 5 (THROW) | Build-up melody |
| 3 (PULL) | 6 (PULL) | Build-up melody |
| 4 (TURN) | 7 (TURN) | Build-up melody |
| 5 (DONE) | 9 (SHOW_RESULT) | Victory arpeggio |

---

### `iclk_gen`
**File**: `iclk_gen.v`  
**Role**: Divides the 100 MHz system clock down to ~4 MHz for the SPI master.

Uses a counter that toggles at counts 12 and 24 (period = 25 cycles), producing a 4 MHz clock with ~52% duty cycle. This satisfies the ADXL362's SPI timing requirements (max SCLK = 8 MHz).

---

### `spi_master`
**File**: `spi_master.v`  
**Role**: Full SPI master for the ADXL362 accelerometer. Handles initialization (write mode register) and continuous data reads.

**Operation Sequence**:
1. **Power-up wait** — 6 ms delay for the sensor to reach standby mode.
2. **SPI Write** — Sends write command (`0x0A`), register address (`0x2D`), and data (`0x02`) to put the ADXL362 into measurement mode.
3. **First-data wait** — 40 ms delay for valid data after mode change.
4. **SPI Read loop** — Sends read command (`0x0B`) and address (`0x0E`), then clocks in 6 bytes (X LSB/MSB, Y LSB/MSB, Z LSB/MSB). After each read, waits 10 ms (~100 Hz sample rate) and loops.

**Data packing**: From each 16-bit axis register, bits [11:7] are extracted (sign + 4 magnitude bits). The three 5-bit values are concatenated into a 15-bit output: `acl_data = {X[11:7], Y[11:7], Z[11:7]}`.

The SPI operates in Mode 0 (CPOL=0, CPHA=0) at 1 MHz (derived from the 4 MHz input by a divide-by-2 toggle). The 93-state FSM bit-bangs every SPI clock edge explicitly.

---

### `action_fsm`
**File**: `action_fsm.v`  
**Role**: Core game logic. A 6-state FSM that sequences the game phases and evaluates gesture scoring.

**States**:
| State | Duration | Description |
|-------|----------|-------------|
| `S_IDLE` (0) | Instant | Waiting for `sw` = 1. Resets score and baselines. |
| `S_INIT` (1) | 4 seconds | Countdown / baseline calibration. Keep the board still. |
| `S_THROW` (2) | 8 seconds | Throw detection phase. |
| `S_PULL` (3) | 8 seconds | Pull detection phase. |
| `S_TURN` (4) | 8 seconds | Turn detection phase. |
| `S_DONE` (5) | Indefinite | Display final score. `sw` = 0 resets to IDLE. |

**Scoring algorithms**:

- **Self-calibrating baseline**: While idle, `base_x` and `base_z` snap to the live accelerometer reading. During gameplay, they slowly track the reading (1 step per `BASE_PERIOD` = 1/16 second). This absorbs gravity and tilt while letting fast gestures create detectable deviations.

- **THROW**: Requires a two-step gesture — first a Z-axis spike (deviation ≥ 5 from baseline), then an X-axis spike. Uses rising-edge detection so only the onset of each spike counts. A 0.25-second cooldown prevents double-counting.

- **PULL**: An X-axis deviation ≥ 2 from baseline (either direction) scores a point. Rising-edge detected with 0.25-second cooldown. Lower threshold makes this the easiest phase.

- **TURN**: Counts sign flips on Y and Z axes (the board is being rotated). When the combined flip count reaches 2, a point is awarded. Uses the same 0.25-second cooldown.

**Timer output**: `timer_sec` shows seconds remaining in the current phase (counts down from 4 during INIT, from 8 during action phases).

---

### `seg7_control`
**File**: `seg7_control.v`  
**Role**: Drives the 8-digit multiplexed 7-segment display on the Nexys A7.

**Display layout**:
```
AN7  AN6  AN5  AN4  AN3  AN2  AN1  AN0
 T    T   off  off  off  off   S    S
```
- **AN0–AN1**: Player score (ones and tens digits)
- **AN6–AN7**: Countdown timer (ones and tens digits)
- **AN2–AN5**: Blank (off)

Converts binary score (0–99) and timer (0–9) to BCD using division/modulo, then scans through active anodes at ~1 ms per digit (125 Hz full refresh). Each digit is decoded to a 7-bit segment pattern (active-low).

---

### `VGA_TEST`
**File**: `VGA_TEST.v`  
**Role**: Top-level VGA display controller. Manages game visual states, animation frame switching, sprite rendering, and text overlay composition.

**Internal state machine** (7 states, driven by `sw`):
| State | Duration | Visual |
|-------|----------|--------|
| 0 | Until sw=1 | Menu text: "PRESS BUTTON TO START" |
| 1–4 | 1 second each | Countdown: "3", "2", "1", "START" |
| 5 | 3 × 8 seconds | Gameplay animations (throw → pull → turn) |
| 6 | Indefinite | Result screen with score |

**Animation system**: 9 `IMAGE_ROM` instances hold 3 frames for each of the 3 motions (throw, pull, turn). A 6 FPS frame looper (driven by vsync falling edge, firing every 10th vsync = ~6 Hz) cycles through the 3 frames for the current motion.

**Sprite rendering**: Each 160×120 pixel sprite is scaled 4× to fill the 640×480 display. The ROM address maps VGA coordinates to sprite pixels: `address = (y/4) × 160 + (x/4)`.

**Screen composition priority**:
1. White text pixels (menu/countdown states)
2. Yellow text pixels (result screen)
3. Sprite animation (gameplay state)
4. Black background (everywhere else)

---

### `VGA`
**File**: `VGA.v`  
**Role**: Standard VGA timing signal generator for 640×480 @ 60 Hz.

Divides the 100 MHz clock by 4 to get a 25 MHz pixel clock. Generates horizontal and vertical counters, sync pulses (active-low), and a `video_on` flag that is high only within the 640×480 active region.

**Timing parameters** (industry standard):
| | Display | Front Porch | Sync Pulse | Back Porch | Total |
|--|---------|-------------|------------|------------|-------|
| Horizontal | 640 | 16 | 96 | 48 | 800 pixels |
| Vertical | 480 | 10 | 2 | 33 | 525 lines |

---

### `IMAGE_ROM`
**File**: `IMAGE_ROM.v`  
**Role**: Parameterized synchronous ROM for storing sprite images. Each instance holds one 160×120 pixel frame in 12-bit color (4 bits per R/G/B channel).

Memory size: 19,200 entries × 12 bits. Loaded at synthesis time from a `.hex` file specified by the `HEX_FILE` parameter. Synchronous read (BRAM-inferred).

---

### `UI_TEXT_ENGINE`
**File**: `UI_TEXT_ENGINE.v`  
**Role**: Combinational bitmap text renderer. Draws text strings on the VGA screen by looking up characters in a built-in 8×8 pixel font ROM.

**Screens rendered**:
- **State 0 (Menu)**: "PRESS BUTTON" and "TO START" (4× scale)
- **States 1–3 (Countdown)**: "3", "2", "1" (8× scale, centered)
- **State 4**: "START" (8× scale)
- **State 6 (Result)**: "RESULT" (8× scale) and "SCORE: XX" (4× scale, with BCD conversion)

The font ROM contains hand-coded 8×8 bitmaps for digits 0–9 and uppercase letters A, B, C, E, L, N, O, P, R, S, T, U, plus the colon character. Each character is stored as 8 bytes (one per row), with bits indicating pixel-on/off.

---

### `main_game_audio_processor`
**File**: `main_game_audio_processor.v`  
**Role**: PWM audio engine that plays different melodies and sound effects based on the current game state.

**Audio tracks by state**:
| Game State | Track | Tempo |
|------------|-------|-------|
| HOLD (1) | Silence | — |
| INPUT_START / DISP_START (2–3) | Verse melody (E4-G4-A4-C5-D5 pattern) | 166 ms/step |
| COUNTDOWN (4) | Short beep tick (25 ms burst) | 166 ms/step |
| THROW / PULL / TURN (5–7) | Build-up melody (Ode to Joy pattern) | 250 ms/step |
| SHOW_RESULT (9) | Victory arpeggio (C4-E4-G4-C5 loop) | 166 ms/step |

**Sound generation**: Uses `note_generator` instances — clock divider square wave generators. A note divisor value determines the frequency (e.g., 113636 → ~440 Hz = A4 at 100 MHz clock). A drum channel uses a rapid toggle of `tempo_counter[14]` to create a pseudo-noise rhythm.

**Mixing**: A 2-bit PWM DAC sums melody, SFX, and drum channels. An 80/20 gate (80% sound, 20% silence per step) creates a staccato articulation effect.

**Mute logic**: Audio is forced to zero when `master_sw` = 0 or the game is in HOLD state.

---

### `note_generator`
**File**: `main_game_audio_processor.v` (same file, second module)  
**Role**: Simple clock-divider square wave oscillator. Divides the 100 MHz clock by `note_div` to produce a square wave at the target audio frequency. Output is 0 when `note_div` = 0 (rest/silence).

---

### `scoring_design`
**File**: `scoring_design.v`  
**Role**: **Legacy/unused** — An earlier version of the scoring system (`scoring_system` module). Uses a different approach with absolute thresholds and per-phase score caps of 10 points (max 30 total), plus a rank system (Try Again / Okay / Excellent). **Not instantiated** in the current `master_game_top`.

---

### `top`
**File**: `top.v`  
**Role**: **Legacy/unused** — An earlier top-level module that only wired up the accelerometer, SPI, LEDs, and 7-segment display. Predates the game logic, VGA, and audio additions. **Not instantiated** — `master_game_top` is the active top module.

---

## Game Flow

```
Power On
   │
   ▼
┌──────────┐   SW0 = 1    ┌──────────┐
│  IDLE    │─────────────►│   INIT   │  4 seconds — Baseline calibration
│ (Menu)   │              │(Countdown)│  Keep the board still!
└──────────┘              └────┬─────┘
   ▲                           │
   │ SW0 = 0              ┌───▼────┐
   │ (any time)            │ THROW  │  8 seconds — Z spike then X spike
   │                       └───┬────┘
   │                           │
   │                       ┌───▼────┐
   │                       │  PULL  │  8 seconds — X deviation (easy)
   │                       └───┬────┘
   │                           │
   │                       ┌───▼────┐
   │                       │  TURN  │  8 seconds — Rotate the board
   │                       └───┬────┘
   │                           │
   │                       ┌───▼────┐
   └───────────────────────│  DONE  │  Final score displayed
                           │(Result)│
                           └────────┘
```

**Total game duration**: 4 + 8 + 8 + 8 = **28 seconds** per round.

**Controls**:
- **SW0 ON** (J15 high): Starts the game from IDLE
- **SW0 OFF** (J15 low): Instantly resets to IDLE from any state, clears score
- **CPU Reset** (C12): Resets VGA and audio subsystems

---

## Pin Mapping

All pin assignments are in `ucf.xdc`. Key mappings:

| Function | FPGA Pin(s) | Nexys A7 Label |
|----------|-------------|----------------|
| System Clock (100 MHz) | E3 | CLK100MHZ |
| Game Switch (SW0) | J15 | SW[0] |
| CPU Reset | C12 | CPU_RESETN |
| Accelerometer SPI | E15, F14, F15, D15 | ACL_MISO/MOSI/SCLK/CSN |
| VGA Red [3:0] | A3, B4, C5, A4 | VGA_R |
| VGA Green [3:0] | C6, A5, B6, A6 | VGA_G |
| VGA Blue [3:0] | B7, C7, D7, D8 | VGA_B |
| VGA HSync / VSync | B11, B12 | VGA_HS / VGA_VS |
| Audio PWM / Shutdown | A11, D12 | AUD_PWM / AUD_SD |
| LEDs [14:0] | H17..V12 | LED[0]..LED[14] |
| 7-Seg Cathodes [6:0] | T10..L18 | CA..CG |
| 7-Seg Anodes [7:0] | J17..U13 | AN[0]..AN[7] |
| Decimal Point | H15 | DP |

---

## Sprite Assets

Nine `.hex` files store the animation frames (160×120 pixels, 12-bit RGB each):

| File | Motion | Frame |
|------|--------|-------|
| `throw_1vga.hex` | Throw | Frame 1 |
| `throw_vga.hex` | Throw | Frame 2 |
| `throw_2vga.hex` | Throw | Frame 3 |
| `pull_1vga.hex` | Pull | Frame 1 |
| `pull_2vga.hex` | Pull | Frame 2 |
| `pull_3vga.hex` | Pull | Frame 3 |
| `turn_1vga.hex` | Turn | Frame 1 |
| `turn_2vga.hex` | Turn | Frame 2 |
| `turn_3vga.hex` | Turn | Frame 3 |

Each file contains 19,200 lines of 3-character hex values (one pixel per line, format `RGB`). These are loaded into BRAM at synthesis time via `$readmemh`.

---

## Building and Programming

1. Open `KKEE2163_Digital_Electronics_Project.xpr` in **Xilinx Vivado 2024.1+**.
2. Verify `master_game_top` is set as the top module.
3. Run **Synthesis** → **Implementation** → **Generate Bitstream**.
4. Connect the Nexys A7-100T via USB and open **Hardware Manager**.
5. Program the device with the generated `.bit` file.
6. Connect a VGA monitor and optionally speakers/headphones to the audio jack.
7. Flip **SW0** up to start the game.
