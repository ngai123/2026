# KKEE2163 Digital Electronics Project — Full Documentation

## Accelerometer Gesture Game on Nexys A7-100T FPGA

---

## 1. Project Overview

This project is an FPGA-based gesture-recognition game built on the **Digilent Nexys A7-100T** board (Xilinx Artix-7). The player physically moves the board to perform three gestures — **Throw**, **Pull**, and **Turn** — which are detected by the on-board **ADXL362 accelerometer** via SPI. The game provides real-time feedback through four output channels:

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   ┌────────┐                      ┌────────────────────┐        │
│   │ VGA    │  640×480 display     │  7-Segment Display │        │
│   │ Monitor│  Sprite animations   │  Score + Countdown │        │
│   │        │  Menu / Result text  │                    │        │
│   └────────┘                      └────────────────────┘        │
│                                                                 │
│   ┌────────┐                      ┌────────────────────┐        │
│   │ Audio  │  PWM melodies        │  15 LEDs           │        │
│   │ Output │  Per-phase music     │  Raw accel. data   │        │
│   │        │  Victory jingle      │  X[14:10] Y[9:5]   │        │
│   └────────┘                      │  Z[4:0]            │        │
│                                   └────────────────────┘        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Hardware Requirements

```
┌──────────────────────────────────────────────────────────────────┐
│                    NEXYS A7-100T BOARD                            │
│                                                                  │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────────────┐   │
│  │ADXL362  │  │ Artix-7  │  │ VGA     │  │ 7-Segment (x8)   │   │
│  │Accel.   │──│ XC7A100T │──│ Port    │  │ ┌──┬──┬──┬──┐    │   │
│  │(SPI)    │  │ FPGA     │  │ (DB15)  │  │ │07│06│  │  │    │   │
│  └─────────┘  │          │──│         │  │ │TT│TT│--│--│    │   │
│               │          │  └─────────┘  │ ├──┼──┼──┼──┤    │   │
│  ┌─────────┐  │          │               │ │--│--│01│00│    │   │
│  │ SW0     │──│          │──┌─────────┐  │ │--│--│SS│SS│    │   │
│  │ (J15)   │  │          │  │ Audio   │  │ └──┴──┴──┴──┘    │   │
│  └─────────┘  │          │  │ AUD_PWM │  │ T=Timer S=Score  │   │
│               │          │  │ AUD_SD  │  └──────────────────┘   │
│  ┌─────────┐  │          │  └─────────┘                         │
│  │CPU Reset│──│          │                                       │
│  │ (C12)   │  │          │──┌──────────────────────────────┐     │
│  └─────────┘  └──────────┘  │ LED[14] ... LED[10] │ X data │     │
│                             │ LED[9]  ... LED[5]  │ Y data │     │
│                             │ LED[4]  ... LED[0]  │ Z data │     │
│                             └──────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────┘
```

| Component | Detail |
|-----------|--------|
| FPGA Board | Digilent Nexys A7-100T (Artix-7 XC7A100T) |
| Accelerometer | ADXL362 (on-board, SPI interface) |
| Display | VGA monitor (640×480 @ 60 Hz) via DB15 connector |
| Audio | On-board PWM audio amplifier (Pin A11 / D12) |
| Controls | Switch SW0 (J15) — start/reset; CPU Reset button (C12) |
| Indicators | 15 LEDs (raw accel data), 8-digit 7-segment display |

---

## 3. Complete System Architecture

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║                            master_game_top.v                                 ║
║                                                                              ║
║  CLK100MHZ ─────┬──────────────────────────────────────────────────────────── ║
║                 │                                                            ║
║                 ▼                                                            ║
║          ┌─────────────┐       ┌───────────────────┐                         ║
║          │  iclk_gen   │       │    spi_master      │       ┌──────┐         ║
║          │             │ 4MHz  │                    │  SPI  │ADXL  │         ║
║          │ 100MHz→4MHz │──────►│ Init + Continuous  │◄─────►│362   │         ║
║          │             │       │ Read @ 100 Hz      │ Pins  │Accel │         ║
║          └─────────────┘       └────────┬───────────┘       └──────┘         ║
║                                         │                                    ║
║                              acl_data[14:0]                                  ║
║                    ┌────────────┼────────────────┐                           ║
║                    │            │                │                            ║
║                    ▼            ▼                ▼                            ║
║  sw ──────► ┌──────────────┐  ┌──────────┐  ┌────────────┐                   ║
║  (J15)      │  action_fsm  │  │ VGA_TEST │  │ LED[14:0]  │                   ║
║             │              │  │          │  │ = acl_data  │                   ║
║             │ Game Logic   │  │ VGA Top  │  └────────────┘                   ║
║             │ & Scoring    │  │ Module   │                                   ║
║             └──┬───┬───┬───┘  └──┬───────┘                                   ║
║                │   │   │        │                                            ║
║           score│timer│state│     │                                            ║
║           [7:0]│[3:0]│[2:0]     │ VGA R/G/B [3:0] each                       ║
║                │   │   │        │ HSync, VSync                               ║
║                ▼   │   │        ▼                                            ║
║         ┌──────────┴───┤   ┌──────────┐                                      ║
║         │ seg7_control │   │          │────► VGA Monitor                      ║
║         │              │   │  Wires   │      640×480 @ 60Hz                  ║
║         │ 7-Seg Driver │   │          │                                      ║
║         └──────────────┘   └──────────┘                                      ║
║                    │                                                         ║
║              state_out ──► audio_state_mapped (remapped)                     ║
║                                   │                                          ║
║                                   ▼                                          ║
║                    ┌──────────────────────────────┐                           ║
║                    │ main_game_audio_processor     │                          ║
║                    │                              │                           ║
║                    │  ┌─────────────┐ ┌────────┐ │                           ║
║                    │  │note_generator│ │note_gen│ │                           ║
║                    │  │(melody)      │ │(SFX)   │ │───► AUD_PWM              ║
║                    │  └─────────────┘ └────────┘ │───► AUD_SD                ║
║                    │  + drum noise channel        │                           ║
║                    └──────────────────────────────┘                           ║
║                                                                              ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

### Data Flow (Numbered Steps)

```
  ① 100 MHz clock from Nexys A7 crystal oscillator
           │
           ▼
  ② iclk_gen divides to 4 MHz for SPI timing
           │
           ▼
  ③ spi_master initializes ADXL362, reads X/Y/Z every 10 ms
           │
           ▼
  ④ 15-bit acl_data packed: {X_sign,X_mag[3:0], Y_sign,Y_mag[3:0], Z_sign,Z_mag[3:0]}
           │
     ┌─────┼─────┬──────────┐
     ▼     ▼     ▼          ▼
  ⑤ FSM  ⑥ VGA  ⑦ LEDs   ⑧ Audio
     │     │     (direct)    │
     │     │                 │
  Score  Sprites          Melodies
  Timer  Text             SFX
```

---

## 4. File Structure

```
KKEE2163_Digital_Electronics_Project/
│
├── documentation.md ◄─────────────────── You are here
├── README.md
├── .gitignore
├── KKEE2163_Digital_Electronics_Project.xpr    ← Vivado project file
│
├── KKEE2163_Digital_Electronics_Project.srcs/
│   ├── sources_1/new/                          ← ALL Verilog source files
│   │   │
│   │   │  ┌─────────── ACTIVE (instantiated in master_game_top) ───────────┐
│   │   │  │                                                                 │
│   │   ├──│── master_game_top.v ·········· Top-level: wires everything      │
│   │   ├──│── action_fsm.v ·············· Game FSM: scoring + timer         │
│   │   ├──│── spi_master.v ·············· ADXL362 SPI driver (93 states!)   │
│   │   ├──│── iclk_gen.v ················ Clock: 100 MHz → 4 MHz            │
│   │   ├──│── seg7_control.v ············ 7-segment display multiplexer     │
│   │   ├──│── VGA_TEST.v ················ VGA top: sprites + UI + state      │
│   │   ├──│── VGA.v ····················· VGA timing (640×480 @ 60 Hz)      │
│   │   ├──│── IMAGE_ROM.v ··············· Parameterized sprite BRAM ROM     │
│   │   ├──│── UI_TEXT_ENGINE.v ·········· Bitmap font renderer (8×8 ASCII)  │
│   │   ├──│── main_game_audio_processor.v PWM audio + note_generator        │
│   │   │  │                                                                 │
│   │   │  └─────────────────────────────────────────────────────────────────┘
│   │   │
│   │   │  ┌─────────── LEGACY (not instantiated, kept for reference) ──────┐
│   │   ├──│── scoring_design.v ·········· Old scoring system (unused)       │
│   │   └──│── top.v ···················· Old top module (unused)            │
│   │      └─────────────────────────────────────────────────────────────────┘
│   │
│   └── constrs_1/new/
│       └── ucf.xdc ······················ Pin constraints for Nexys A7
│
│  ┌────────── SPRITE ANIMATION FRAMES (160×120 px, 12-bit RGB each) ────────┐
│  │                                                                          │
├──│── throw_1vga.hex ····· Throw animation frame 1 (arms raised)            │
├──│── throw_vga.hex ······ Throw animation frame 2 (arms extended)          │
├──│── throw_2vga.hex ····· Throw animation frame 3 (follow-through)         │
├──│── pull_1vga.hex ······ Pull animation frame 1 (standing)                │
├──│── pull_2vga.hex ······ Pull animation frame 2 (pulling back)            │
├──│── pull_3vga.hex ······ Pull animation frame 3 (crouched)                │
├──│── turn_1vga.hex ······ Turn animation frame 1 (facing forward)          │
├──│── turn_2vga.hex ······ Turn animation frame 2 (mid-rotation)            │
└──│── turn_3vga.hex ······ Turn animation frame 3 (rotated)                 │
   └──────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Sprite Animation Frames — Visual Comparison

All sprites are **160×120 pixel grayscale images** stored as 12-bit hex RGB values (`000` = black, `FFF` = white). They are rendered on-screen at **4× scale** (640×480), looping at **~6 FPS**.

### 5.1 THROW Animation (3 Frames)

The throw animation shows a character performing a forward throwing motion:

```
  FRAME 1 (throw_1vga.hex)       FRAME 2 (throw_vga.hex)        FRAME 3 (throw_2vga.hex)
  1784 non-black pixels           1737 non-black pixels           1592 non-black pixels
  Arms raised, winding up         Arms extended forward           Follow-through pose

  ┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
  │    ╔════ TEXT ════╗   │    │    ╔════ TEXT ════╗   │    │    ╔════ TEXT ════╗   │
  │    ╚══════════════╝   │    │    ╚══════════════╝   │    │    ╚══════════════╝   │
  │                       │    │                       │    │                       │
  │                       │    │                       │    │                       │
  │                       │    │                       │    │                       │
  │         ┌─○           │    │         ┌─○           │    │           ○           │
  │        ╱│╲──→         │    │        ╱│╲────→       │    │          ╱│╲──→       │
  │       ╱ │ ╲           │    │        │ ╲            │    │         ╱ │  ╲        │
  │         │             │    │        │              │    │           │           │
  │        ╱ ╲            │    │       ╱ ╲             │    │          ╱ ╲          │
  │       ╱   ╲           │    │      ╱   ╲            │    │         ╱   ╲         │
  │      ╱     ╲          │    │     ╱     ╲           │    │        ╱     ╲        │
  └──────────────────────┘    └──────────────────────┘    └──────────────────────┘

  Key differences:
  ● Frame 1: Widest pose (x: 32-141), arms pulled back to generate force
  ● Frame 2: Arms thrust forward (x: 28-126), body leaning into throw
  ● Frame 3: Smallest frame (x: 32-128), compact follow-through
```

### 5.2 PULL Animation (3 Frames)

The pull animation shows a character pulling backward. Frame 3 is dramatically different — the character is crouched very low with minimal visible body:

```
  FRAME 1 (pull_1vga.hex)       FRAME 2 (pull_2vga.hex)        FRAME 3 (pull_3vga.hex)
  1127 non-black pixels          1035 non-black pixels           743 non-black pixels
  Standing upright               Leaning back                    Crouched / pulled back

  ┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
  │    ╔════ TEXT ════╗   │    │    ╔════ TEXT ════╗   │    │    ╔════ TEXT ════╗   │
  │    ╚══════════════╝   │    │    ╚══════════════╝   │    │    ╚══════════════╝   │
  │                       │    │                       │    │                       │
  │                       │    │                       │    │                       │
  │          ○            │    │          ○            │    │                       │
  │       ←─│╲            │    │     ←──╱│╲           │    │                       │
  │         │ ╲           │    │       ╱ │            │    │                       │
  │         │             │    │      ╱  │            │    │                       │
  │        ╱ ╲            │    │        ╱ ╲           │    │                       │
  │       ╱   ╲           │    │       ╱   ╲          │    │          ○            │
  │      ╱     ╲          │    │       ╲    ╲         │    │       ←═╱│╲           │
  │                       │    │         ╲            │    │        ╱ ╲            │
  └──────────────────────┘    └──────────────────────┘    └──────────────────────┘

  Key differences:
  ● Frame 1: Full standing figure (1127 px), arms at sides → most detail
  ● Frame 2: Body tilting backward (1035 px), arms reaching behind
  ● Frame 3: Extreme crouch (743 px — FEWEST pixels of ANY frame)
             Most of the figure is near the bottom of the sprite
             Represents the fully-pulled-back position
```

### 5.3 TURN Animation (3 Frames)

The turn animation shows the character rotating their body. The figure's orientation shifts across frames:

```
  FRAME 1 (turn_1vga.hex)       FRAME 2 (turn_2vga.hex)        FRAME 3 (turn_3vga.hex)
  1336 non-black pixels          1330 non-black pixels           1119 non-black pixels
  Facing forward                 Mid-rotation                    Rotated sideways

  ┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
  │    ╔════ TEXT ════╗   │    │    ╔════ TEXT ════╗   │    │    ╔════ TEXT ════╗   │
  │    ╚══════════════╝   │    │    ╚══════════════╝   │    │    ╚══════════════╝   │
  │                       │    │                       │    │                       │
  │                       │    │                       │    │                       │
  │                       │    │                       │    │                       │
  │         ○             │    │         ○             │    │           ○           │
  │       ╱ │ ╲           │    │      ╱╱│╲            │    │          ╱│           │
  │    ↺ ╱  │  ╲ ↻        │    │     ╱  │  ↻          │    │         ╱ │  ↻        │
  │         │             │    │        │              │    │          │           │
  │        ╱ ╲            │    │       ╱ ╲             │    │         ╱ ╲          │
  │       ╱   ╲           │    │      ╱   ╲            │    │        ╱   ╲         │
  │      ╱     ╲          │    │     ╱     ╲           │    │       ╱     ╲        │
  └──────────────────────┘    └──────────────────────┘    └──────────────────────┘

  Key differences:
  ● Frame 1: Widest spread (x: 38-121, 84px wide), arms out to sides
  ● Frame 2: Similar pixel count (1330), body mid-twist, some color pixels
             (has unique colors like 545, 655, CBC, FEE — blending artifacts)
  ● Frame 3: Narrower (x: 47-122, 76px), most compact, body turned sideways
```

### 5.4 Frame Size Comparison Chart

```
  Non-black pixels per frame:
  
  2000 ┤
       │
  1800 ┤  ████
       │  ████ ████
  1600 ┤  ████ ████ ████
       │  ████ ████ ████                            ████ ████
  1400 ┤  ████ ████ ████                            ████ ████
       │  ████ ████ ████           ████             ████ ████
  1200 ┤  ████ ████ ████  ████    ████             ████ ████ ████
       │  ████ ████ ████  ████    ████    ░░░░     ████ ████ ████
  1000 ┤  ████ ████ ████  ████    ████    ░░░░     ████ ████ ████
       │  ████ ████ ████  ████    ████    ░░░░     ████ ████ ████
   800 ┤  ████ ████ ████  ████    ████    ░░░░     ████ ████ ████
       │  ████ ████ ████  ████    ████  ████████   ████ ████ ████
   600 ┤  ████ ████ ████  ████    ████  ████████   ████ ████ ████
       │  T1    T2    T3    P1      P2     P3       R1    R2    R3
       │  1784  1737  1592  1127   1035    743     1336  1330  1119
       │
       │ ◄──── THROW ────► ◄───── PULL ─────► ◄───── TURN ─────►
       │
  
  Observation: Pull Frame 3 has the fewest pixels (743) — the character is 
  crouched into the smallest pose. Throw frames have the most pixels overall.
```

### 5.5 How Frames Map to ROM Instances in VGA_TEST

```
  active_frame value ──► IMAGE_ROM instance ──► hex file
  
  ┌─────────────┬─────────────────┬───────────────────┐
  │ active_frame│ ROM Instance    │ Hex File          │
  ├─────────────┼─────────────────┼───────────────────┤
  │      0      │ rom_frame_1     │ throw_1vga.hex    │
  │      1      │ rom_frame_2     │ throw_vga.hex     │
  │      2      │ rom_frame_prompt│ throw_2vga.hex    │
  ├─────────────┼─────────────────┼───────────────────┤
  │      3      │ rom_pull_1      │ pull_1vga.hex     │
  │      4      │ rom_pull_2      │ pull_2vga.hex     │
  │      5      │ rom_pull_3      │ pull_3vga.hex     │
  ├─────────────┼─────────────────┼───────────────────┤
  │      6      │ rom_turn_1      │ turn_1vga.hex     │
  │      7      │ rom_turn_2      │ turn_2vga.hex     │
  │      8      │ rom_turn_3      │ turn_3vga.hex     │
  └─────────────┴─────────────────┴───────────────────┘
  
  Animation is driven by animation_state:
    animation_state = 0 → cycles active_frame through 0,1,2 (THROW)
    animation_state = 1 → cycles active_frame through 3,4,5 (PULL)
    animation_state = 2 → cycles active_frame through 6,7,8 (TURN)
```

---

## 6. Game Flow — Complete State Diagram

```
  ╔══════════════════════════════════════════════════════════════════════╗
  ║                        GAME STATE MACHINE                           ║
  ╚══════════════════════════════════════════════════════════════════════╝

  Power On
     │
     ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                         S_IDLE (State 0)                          │
  │                                                                    │
  │  VGA: "PRESS BUTTON TO START"    Score: 0    Timer: 0             │
  │  Audio: Silence                  LEDs: Live accel data            │
  │  Baseline: Snaps to live accel   7-Seg: 00 (score) / 00 (timer)  │
  │                                                                    │
  │  ● All registers reset           ● Baselines calibrate to gravity │
  └──────────────────────────┬─────────────────────────────────────────┘
                             │ SW0 = 1 (switch flipped ON)
                             ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                         S_INIT (State 1)                          │
  │                         Duration: 4 seconds                       │
  │                                                                    │
  │  VGA: Countdown "3" → "2" → "1" → "START"                        │
  │  Audio: Short beep tick each second                               │
  │  7-Seg Timer: 4 → 3 → 2 → 1                                     │
  │                                                                    │
  │  ● KEEP THE BOARD STILL! Baselines are calibrating.               │
  │  ● No scoring happens in this phase.                              │
  └──────────────────────────┬─────────────────────────────────────────┘
                             │ 4 seconds elapsed
                             ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                        S_THROW (State 2)                          │
  │                        Duration: 8 seconds                        │
  │                                                                    │
  │  VGA: Throw sprite animation (frames 0,1,2 at 6 FPS)             │
  │  Audio: Build-up melody (Ode to Joy) at 250ms/step                │
  │  7-Seg Timer: 8 → 7 → 6 → 5 → 4 → 3 → 2 → 1                   │
  │                                                                    │
  │  Scoring: Z-spike arms → X-spike scores (details in §8.1)        │
  │  ● Edge-detected (one point per spike onset)                      │
  │  ● 0.25 sec cooldown between points                               │
  └──────────────────────────┬─────────────────────────────────────────┘
                             │ 8 seconds elapsed
                             ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                         S_PULL (State 3)                          │
  │                         Duration: 8 seconds                       │
  │                                                                    │
  │  VGA: Pull sprite animation (frames 3,4,5 at 6 FPS)              │
  │  Audio: Build-up melody continues                                  │
  │  7-Seg Timer: 8 → 7 → 6 → 5 → 4 → 3 → 2 → 1                   │
  │                                                                    │
  │  Scoring: X deviation spike ≥ 2 from baseline (details in §8.2)  │
  │  ● Easiest phase (lowest threshold)                               │
  │  ● 0.25 sec cooldown between points                               │
  └──────────────────────────┬─────────────────────────────────────────┘
                             │ 8 seconds elapsed
                             ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                         S_TURN (State 4)                          │
  │                         Duration: 8 seconds                       │
  │                                                                    │
  │  VGA: Turn sprite animation (frames 6,7,8 at 6 FPS)              │
  │  Audio: Build-up melody continues                                  │
  │  7-Seg Timer: 8 → 7 → 6 → 5 → 4 → 3 → 2 → 1                   │
  │                                                                    │
  │  Scoring: Y/Z sign flips → every 2 flips = 1 point (§8.3)       │
  │  ● 0.25 sec cooldown between points                               │
  └──────────────────────────┬─────────────────────────────────────────┘
                             │ 8 seconds elapsed
                             ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │                         S_DONE (State 5)                          │
  │                         Duration: Indefinite                      │
  │                                                                    │
  │  VGA: "RESULT" + "SCORE: XX" (yellow text on black)               │
  │  Audio: Victory arpeggio (C4 → E4 → G4 → C5 loop)               │
  │  7-Seg: Final score displayed, timer = 0                          │
  │                                                                    │
  │  ● Score is frozen. Flip SW0 OFF to reset.                        │
  └────────────────────────────────────────────────────────────────────┘
         │
         │ SW0 = 0 (switch flipped OFF) — FROM ANY STATE
         │
         └──────────────► Back to S_IDLE (instant hard reset)


  ┌──────────────────────────────────────┐
  │          TIMELINE SUMMARY            │
  │                                      │
  │  INIT     THROW      PULL     TURN   │
  │ ├──4s──┤├────8s────┤├──8s───┤├──8s──┤│
  │ 0      4           12       20     28│
  │                                      │
  │        Total game: 28 seconds        │
  └──────────────────────────────────────┘
```

---

## 7. Module-by-Module Reference

### 7.1 master_game_top — Top-Level Wiring

```
  ┌─ master_game_top ─────────────────────────────────────────────────────┐
  │                                                                       │
  │  INPUTS                              OUTPUTS                         │
  │  ───────                             ────────                         │
  │  CLK100MHZ ──┬──────────────────────► LED[14:0]  (= acl_data)       │
  │              │                                                        │
  │  reset_btn ──┼──────────────────────► vga_r/g/b[3:0]                 │
  │              │                        vga_hsync, vga_vsync            │
  │  sw ─────────┼──────────────────────►                                 │
  │              │                        SEG[6:0], DP, AN[7:0]          │
  │  ACL_MISO ───┤                                                        │
  │              │                        AUD_PWM, AUD_SD                │
  │              │                        ACL_MOSI, ACL_SCLK, ACL_CSN    │
  │              │                                                        │
  │  INSTANTIATES:                                                        │
  │  ─────────────                                                        │
  │  ① iclk_gen          (100 MHz → 4 MHz)                               │
  │  ② spi_master        (SPI ↔ ADXL362)                                 │
  │  ③ seg7_control      (score + timer → 7-seg)                         │
  │  ④ action_fsm        (game logic FSM)                                │
  │  ⑤ VGA_TEST          (sprites + text → VGA)                          │
  │  ⑥ main_game_audio_processor (melody → PWM)                         │
  │                                                                       │
  └───────────────────────────────────────────────────────────────────────┘
```

**Port table:**

| Port | Dir | Width | Description |
|------|-----|-------|-------------|
| `CLK100MHZ` | in | 1 | 100 MHz system clock |
| `reset_btn` | in | 1 | CPU reset (active-low) |
| `sw` | in | 1 | SW0: game start/reset |
| `ACL_MISO` | in | 1 | SPI MISO from ADXL362 |
| `ACL_MOSI` | out | 1 | SPI MOSI to ADXL362 |
| `ACL_SCLK` | out | 1 | SPI clock |
| `ACL_CSN` | out | 1 | SPI chip select (active-low) |
| `LED[14:0]` | out | 15 | Raw accelerometer data |
| `SEG[6:0]` | out | 7 | 7-segment cathodes |
| `DP` | out | 1 | Decimal point |
| `AN[7:0]` | out | 8 | 7-segment anodes |
| `vga_r/g/b[3:0]` | out | 4 ea | VGA 12-bit color |
| `vga_hsync/vsync` | out | 1 ea | VGA sync |
| `AUD_PWM` | out | 1 | Audio PWM |
| `AUD_SD` | out | 1 | Audio amp enable (always 1) |

**State mapping** (action_fsm → audio engine):
```
  action_fsm state          Audio state          Meaning
  ──────────────────        ──────────────       ───────────────
  0 (S_IDLE)          ──►   1 (HOLD)             Silence
  1 (S_INIT)          ──►   4 (COUNTDOWN)        Beep ticks
  2 (S_THROW)         ──►   5 (THROW)            Build-up melody
  3 (S_PULL)          ──►   6 (PULL)             Build-up melody
  4 (S_TURN)          ──►   7 (TURN)             Build-up melody
  5 (S_DONE)          ──►   9 (SHOW_RESULT)      Victory arpeggio
```

---

### 7.2 iclk_gen — Clock Divider

```
  100 MHz input
     │
     ▼
  ┌──────────────────────────────────────────────────────┐
  │  Counter: 0 → 12 → toggle → 13 → 24 → toggle → 0  │
  │                                                      │
  │  Period = 25 cycles of 100 MHz = 4 MHz output        │
  │  Duty cycle ≈ 52% (13 high, 12 low) — acceptable    │
  └──────────────────────────────────────────────────────┘
     │
     ▼
  4 MHz output → feeds spi_master
```

Why not 50% duty cycle? `100 MHz / 4 MHz / 2 = 12.5` — can't split a clock cycle in half, so the design uses 13/12 split.

---

### 7.3 spi_master — ADXL362 SPI Driver

```
  SPI Bus Wiring:
  
  FPGA (Master)                    ADXL362 (Slave)
  ┌──────────┐                     ┌──────────┐
  │          │─── SCLK (1 MHz) ───►│          │
  │          │─── MOSI ───────────►│          │
  │          │◄── MISO ────────────│          │
  │          │─── CS̄  ────────────►│          │
  └──────────┘                     └──────────┘
  
  SPI Mode 0: CPOL=0, CPHA=0
  Clock: 1 MHz (derived from 4 MHz input by divide-by-2)
```

**93-State FSM Sequence:**

```
  ┌─────────────────────────────────────────────────────────────────┐
  │ PHASE 1: POWER-UP (6 ms wait)                                  │
  │                                                                 │
  │ State: POWER_UP                                                 │
  │ ● Wait 24,000 ticks (6 ms at 4 MHz)                            │
  │ ● CS = 1 (inactive), SCLK = 0                                  │
  └────────────────────────────┬────────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │ PHASE 2: SPI WRITE — Configure Measurement Mode                │
  │                                                                 │
  │ CS goes LOW, then send 3 bytes bit-by-bit:                      │
  │                                                                 │
  │   Byte 1: 0x0A (Write command)                                  │
  │     ┌──┬──┬──┬──┬──┬──┬──┬──┐                                  │
  │     │0 │0 │0 │0 │1 │0 │1 │0 │  States: SEND_WCMD7..0          │
  │     └──┴──┴──┴──┴──┴──┴──┴──┘                                  │
  │                                                                 │
  │   Byte 2: 0x2D (Register address — mode control)                │
  │     ┌──┬──┬──┬──┬──┬──┬──┬──┐                                  │
  │     │0 │0 │1 │0 │1 │1 │0 │1 │  States: SEND_WADDR7..0         │
  │     └──┴──┴──┴──┴──┴──┴──┴──┘                                  │
  │                                                                 │
  │   Byte 3: 0x02 (Measurement mode enable)                        │
  │     ┌──┬──┬──┬──┬──┬──┬──┬──┐                                  │
  │     │0 │0 │0 │0 │0 │0 │1 │0 │  States: SEND_BYTE7..0          │
  │     └──┴──┴──┴──┴──┴──┴──┴──┘                                  │
  │                                                                 │
  │ CS goes HIGH, SCLK disabled                                     │
  └────────────────────────────┬────────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │ PHASE 3: WAIT FOR FIRST DATA (40 ms)                            │
  │                                                                 │
  │ State: WAIT                                                     │
  │ ● 160,000 ticks at 4 MHz = 40 ms                               │
  │ ● Sensor needs this to produce first valid measurement          │
  └────────────────────────────┬────────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │ PHASE 4: SPI READ LOOP (repeats indefinitely)                   │
  │                                                                 │
  │ CS goes LOW, then:                                              │
  │                                                                 │
  │   Send: 0x0B (Read command)       States: SEND_RCMD7..0        │
  │   Send: 0x0E (X LSB address)     States: SEND_RADDR7..0       │
  │                                                                 │
  │   Receive 6 bytes (auto-increment from 0x0E):                   │
  │     0x0E: X LSB [7:0]            States: REC_XLSB7..0          │
  │     0x0F: X MSB [15:8]           States: REC_XMSB7..0          │
  │     0x10: Y LSB [7:0]            States: REC_YLSB7..0          │
  │     0x11: Y MSB [15:8]           States: REC_YMSB7..0          │
  │     0x12: Z LSB [7:0]            States: REC_ZLSB7..0          │
  │     0x13: Z MSB [15:8]           States: REC_ZMSB7..0          │
  │                                                                 │
  │   CS goes HIGH → Wait 10 ms (40,000 ticks) → Loop back          │
  │                                                                 │
  │   Sample rate: ~100 Hz                                          │
  └─────────────────────────────────────────────────────────────────┘
```

**Data packing** — how raw 16-bit register values become 5-bit axis values:

```
  Raw X register (16 bits):
  ┌──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┐
  │15│14│13│12│11│10│ 9│ 8│ 7│ 6│ 5│ 4│ 3│ 2│ 1│ 0│
  └──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┘
                    ▲  ▲  ▲  ▲  ▲
                    │  │  │  │  │
                    └──┴──┴──┴──┘
                    Bits [11:7] extracted
                    = {sign, magnitude[3:0]}

  Final 15-bit acl_data:
  ┌────────────────┬────────────────┬────────────────┐
  │   X [14:10]    │   Y [9:5]      │   Z [4:0]      │
  │ sign + 4 mag   │ sign + 4 mag   │ sign + 4 mag   │
  └────────────────┴────────────────┴────────────────┘
```

---

### 7.4 action_fsm — Game Logic & Scoring

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                    action_fsm Parameters                        │
  ├──────────────────┬───────────────────────────────────────────────┤
  │ CYCLES_PER_SEC   │ 100,000,000 (100 MHz clock)                 │
  │ INIT_SECS        │ 4 seconds                                   │
  │ ACT_SECS         │ 8 seconds per action phase                  │
  │ DTH_THROW        │ 6'd5 — deviation threshold for throw spikes │
  │ DTH_PULL         │ 6'd2 — deviation threshold for pull spikes  │
  │ TH_MOVE          │ 4'd4 — magnitude gate for turn flips        │
  │ COOLDOWN_CYCLES  │ 25,000,000 (0.25 seconds)                   │
  │ BASE_PERIOD      │ 6,250,000 (1/16 second baseline adapt)      │
  └──────────────────┴───────────────────────────────────────────────┘
```

#### 7.4.1 Self-Calibrating Baseline System

```
  During IDLE:                          During Gameplay:
  ┌─────────────────────┐              ┌─────────────────────────────┐
  │ base_x = live X     │              │ Every 1/16 second:          │
  │ base_z = live Z     │              │   if live > base: base += 1 │
  │ (instant snap)      │              │   if live < base: base -= 1 │
  └─────────────────────┘              │ (slow drift tracking)       │
                                       └─────────────────────────────┘

  Why? The board might be held at any tilt. Gravity always contributes
  a constant offset. The baseline absorbs this offset so that only
  MOTION (fast changes) registers as a scorable spike.

  ┌────────── Example: Board held at 30° tilt ──────────┐
  │                                                      │
  │  Accel      ████    ← Throw gesture spike            │
  │  Reading   █    █                                    │
  │           █      █                                   │
  │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ← Baseline    │
  │  ▄▄▄▄▄▄▄▄▄        ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄   (gravity)    │
  │                                                      │
  │  Deviation:  │████│ ← This gets scored               │
  │  (above baseline)                                    │
  └──────────────────────────────────────────────────────┘
```

#### 7.4.2 THROW Scoring (Two-Step Gesture)

```
  Step 1: Z-axis spike arms the throw
  Step 2: X-axis spike within the same phase scores

  Timeline:
  ─────────────────────────────────────────────────────────►
                 Z spike        X spike
                   │               │
                   ▼               ▼
  Z deviation: ▄▄▄█████▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄  (threshold = 5)
                   ↑
               throw_armed = 1
  
  X deviation: ▄▄▄▄▄▄▄▄▄▄▄▄▄▄█████▄▄▄▄▄▄  (threshold = 5)
                                  ↑
                              SCORE +1!
                              throw_armed = 0
                              cooldown = 0.25s

  ● Rising-edge detected: only the ONSET of crossing the threshold counts
  ● Both Z and X must exceed DTH_THROW (5) from baseline
  ● The two spikes don't need to overlap — Z just needs to happen first
```

#### 7.4.3 PULL Scoring (Single Spike)

```
  X deviation from baseline ≥ DTH_PULL (2) → SCORE!
  
  Timeline:
  ─────────────────────────────────────────────────────────►
            spike       spike          spike
              │           │              │
              ▼           ▼              ▼
  X dev:  ▄▄▄███▄▄▄▄▄▄▄███▄▄▄▄▄▄▄▄▄▄███▄▄▄  (threshold = 2)
              ↑           ↑              ↑
           +1 point    +1 point      +1 point
           │←─0.25s──►│
            cooldown

  ● Lowest threshold (2) — easiest phase to score
  ● Either direction counts (push or pull along X axis)
  ● Rising-edge detected + 0.25s cooldown debounce
```

#### 7.4.4 TURN Scoring (Sign-Flip Counter)

```
  Y and Z axis sign flips are counted separately.
  Every 2 accumulated flips → 1 point.

  Y axis sign:  + + + - - - + + + - - - + + 
                        ↑           ↑       ↑
                      flip 1      flip 2  flip 3
  
  Z axis sign:  + + - - - + + + - - - + + + 
                      ↑       ↑       ↑
                    flip 1  flip 2  flip 3

  Combined flip count: 1 → 2 → SCORE → reset → 1 → 2 → SCORE → ...
                              ↑                        ↑
                           +1 point                 +1 point
                           cooldown                 cooldown

  ● Only counts when magnitude ≥ TH_MOVE (4) — ignores noise at rest
  ● Y and Z flips are pooled into one counter
  ● Counter resets to 0 after scoring + during cooldown
```

---

### 7.5 seg7_control — 7-Segment Display

```
  8-Digit Display Layout:
  ┌────┬────┬────┬────┬────┬────┬────┬────┐
  │AN7 │AN6 │AN5 │AN4 │AN3 │AN2 │AN1 │AN0 │
  │    │    │    │    │    │    │    │    │
  │ T  │ T  │OFF │OFF │OFF │OFF │ S  │ S  │
  │tens│ones│    │    │    │    │tens│ones│
  └────┴────┴────┴────┴────┴────┴────┴────┘
    ◄─Timer─►                    ◄─Score─►

  Refresh: 1 ms per digit × 8 digits = 8 ms full cycle (125 Hz)
  
  BCD Conversion (combinational):
    score_tens = (final_marks / 10) % 10
    score_ones = final_marks % 10
    timer_tens = timer_sec / 10
    timer_ones = timer_sec % 10

  Segment encoding (active-low, bit order: gfedcba):
  ┌─────────────────────────────────────┐
  │       aaaa          0: 0000001      │
  │      f    b         1: 1001111      │
  │      f    b         2: 0010010      │
  │       gggg          3: 0000110      │
  │      e    c         4: 1001100      │
  │      e    c         5: 0100100      │
  │       dddd          6: 0100000      │
  │                     7: 0001111      │
  │                     8: 0000000      │
  │                     9: 0000100      │
  └─────────────────────────────────────┘
```

---

### 7.6 VGA_TEST — VGA Display Top Module

```
  ┌─ VGA_TEST ────────────────────────────────────────────────────────────┐
  │                                                                       │
  │  INSTANTIATES:                                                        │
  │                                                                       │
  │  ┌─────────────┐    ┌──────────────────────────────────────────────┐  │
  │  │   VGA       │    │  9 × IMAGE_ROM instances                     │  │
  │  │  (timing)   │    │                                              │  │
  │  │             │    │  ┌────────┐ ┌────────┐ ┌────────┐           │  │
  │  │ x_pos ──────┤    │  │throw_1 │ │throw_2 │ │throw_3 │           │  │
  │  │ y_pos ──────┤    │  └────────┘ └────────┘ └────────┘           │  │
  │  │ video_on ───┤    │  ┌────────┐ ┌────────┐ ┌────────┐           │  │
  │  │ hsync ──────┤    │  │ pull_1 │ │ pull_2 │ │ pull_3 │           │  │
  │  │ vsync ──────┤    │  └────────┘ └────────┘ └────────┘           │  │
  │  └─────────────┘    │  ┌────────┐ ┌────────┐ ┌────────┐           │  │
  │                     │  │ turn_1 │ │ turn_2 │ │ turn_3 │           │  │
  │  ┌─────────────┐    │  └────────┘ └────────┘ └────────┘           │  │
  │  │UI_TEXT_     │    └──────────────────────────────────────────────┘  │
  │  │ENGINE      │                                                      │
  │  │(font ROM)  │    All 9 ROMs share the same rom_address             │
  │  └─────────────┘    (= current pixel mapped to 160×120 space)        │
  │                     The active_frame MUX selects which ROM's output   │
  │                     feeds game_color                                  │
  └───────────────────────────────────────────────────────────────────────┘
```

**VGA_TEST Internal State Machine (7 states):**

```
  master_state │ Duration  │ VGA Output
  ─────────────┼───────────┼─────────────────────────────────
       0       │ Until sw  │ Black screen + white text:
               │           │ "PRESS BUTTON" / "TO START"
  ─────────────┼───────────┼─────────────────────────────────
       1       │ 1 second  │ Black screen + big white "3"
       2       │ 1 second  │ Black screen + big white "2"
       3       │ 1 second  │ Black screen + big white "1"
       4       │ 1 second  │ Black screen + big white "START"
  ─────────────┼───────────┼─────────────────────────────────
       5       │ 3 × 8 sec │ Character sprite animation
               │           │ (cycles through throw/pull/turn)
  ─────────────┼───────────┼─────────────────────────────────
       6       │ Indefinite│ Black screen + yellow text:
               │           │ "RESULT" + "SCORE: XX"
```

**Sprite scaling — how 160×120 fills 640×480:**

```
  ROM pixel (1×1)                   Screen pixel (4×4)
  ┌───┐                             ┌───┬───┬───┬───┐
  │ P │  ──── 4× scale ────►        │ P │ P │ P │ P │
  └───┘                             ├───┼───┼───┼───┤
                                    │ P │ P │ P │ P │
                                    ├───┼───┼───┼───┤
                                    │ P │ P │ P │ P │
                                    ├───┼───┼───┼───┤
                                    │ P │ P │ P │ P │
                                    └───┴───┴───┴───┘

  Address calculation:
  rom_address = ((vga_y >> 2) * 160) + (vga_x >> 2)
  
  This maps every 4×4 block of screen pixels to one ROM pixel.
```

**Screen composition priority (final_vga_color):**

```
  Priority │ Condition                    │ Color
  ─────────┼──────────────────────────────┼──────────────
     1     │ Menu/countdown + text pixel  │ White (FFF)
     2     │ Result screen + text pixel   │ Yellow (FF0)
     3     │ Gameplay + in sprite box     │ game_color (from ROM)
     4     │ Everything else              │ Black (000)
```

**6 FPS animation looper:**

```
  VSync (60 Hz) ──► Count 10 vsync falling edges ──► Switch frame
  
  60 Hz / 10 = 6 frame changes per second
  
  animation_state  │  active_frame cycles through
  ─────────────────┼───────────────────────────────
        0 (throw)  │  0 → 1 → 2 → 0 → 1 → 2 → ...
        1 (pull)   │  3 → 4 → 5 → 3 → 4 → 5 → ...
        2 (turn)   │  6 → 7 → 8 → 6 → 7 → 8 → ...
```

---

### 7.7 VGA — Timing Generator

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                    VGA 640×480 @ 60 Hz Timing                    │
  │                                                                  │
  │  Pixel clock: 25 MHz (100 MHz / 4)                               │
  │                                                                  │
  │  HORIZONTAL (per line):                                          │
  │  ┌──────────┬────────┬──────────┬──────────┐                     │
  │  │ Display  │ Front  │  Sync    │  Back    │                     │
  │  │ 640 px   │Porch   │ Pulse    │ Porch    │  = 800 total       │
  │  │          │ 16 px  │ 96 px    │ 48 px    │                     │
  │  └──────────┴────────┴──────────┴──────────┘                     │
  │  ◄──video_on──►                                                  │
  │                       ◄─hsync─►                                  │
  │                       (active low)                               │
  │                                                                  │
  │  VERTICAL (per frame):                                           │
  │  ┌──────────┬────────┬──────────┬──────────┐                     │
  │  │ Display  │ Front  │  Sync    │  Back    │                     │
  │  │ 480 ln   │Porch   │ Pulse    │ Porch    │  = 525 total       │
  │  │          │ 10 ln  │  2 ln    │ 33 ln    │                     │
  │  └──────────┴────────┴──────────┴──────────┘                     │
  │  ◄──video_on──►                                                  │
  │                       ◄─vsync─►                                  │
  │                       (active low)                               │
  │                                                                  │
  │  Frame rate: 25 MHz / (800 × 525) = 59.52 Hz ≈ 60 Hz            │
  └──────────────────────────────────────────────────────────────────┘
```

---

### 7.8 IMAGE_ROM — Sprite Memory

```
  ┌─────────────────────────────────────────────────────────┐
  │  IMAGE_ROM #(.HEX_FILE("xxxx.hex"))                     │
  │                                                         │
  │  Memory:  reg [11:0] memory_array [0:19199]             │
  │           19,200 entries × 12 bits                      │
  │           = 160 × 120 pixels                            │
  │                                                         │
  │  Address ──► [14:0] ──► memory_array[address]           │
  │                              │                          │
  │                              ▼                          │
  │  color_data ◄── [11:0] ── {R[3:0], G[3:0], B[3:0]}    │
  │                                                         │
  │  Loaded at synthesis: $readmemh(HEX_FILE, memory_array) │
  │  Synchronous read (BRAM-inferred, 1 clock latency)      │
  └─────────────────────────────────────────────────────────┘

  Pixel format:
  ┌────────────┬────────────┬────────────┐
  │  R [11:8]  │  G [7:4]   │  B [3:0]   │
  │  4 bits    │  4 bits    │  4 bits    │
  └────────────┴────────────┴────────────┘
  
  Example: hex value "F80" = R=15, G=8, B=0 = bright orange
           hex value "FFF" = R=15, G=15, B=15 = white
           hex value "000" = black (background)
```

---

### 7.9 UI_TEXT_ENGINE — Bitmap Font Renderer

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                  UI_TEXT_ENGINE — How it works                   │
  │                                                                 │
  │  Input: vga_x, vga_y, master_state                              │
  │  Output: draw_text_pixel (1 = this pixel is text)               │
  │                                                                 │
  │  Step 1: Which screen? (master_state → text layout)             │
  │  Step 2: Is current pixel inside a text bounding box?           │
  │  Step 3: Which character in the string? (x position)            │
  │  Step 4: Look up 8×8 font bitmap for that character             │
  │  Step 5: Is this specific pixel ON in the bitmap?               │
  └─────────────────────────────────────────────────────────────────┘
```

**Font ROM — Built-in 8×8 character bitmaps:**

```
  Available characters and their bitmaps:

  "0"          "1"          "2"          "3"          "A"
  ·█████·      ··██··       ·█████·      ·█████·      ··███··
  █·····█      ·███··       █·····█      █·····█      ·█···█·
  █··█··█      ·█·█··       ····█··      ····█··      █·····█
  █·█···█      ··██··       ··██···      ··███··      ███████
  █····█·      ··██··       ·█·····      ····██·      █·····█
  █·····█      ··██··       █······      █·····█      █·····█
  ·█████·      ·█████·      ███████      ·█████·      █·····█

  "P"          "R"          "E"          "S"          "T"
  ██████·      ██████·      ███████      ·█████·      ███████
  █·····█      █·····█      █······      █·····█      ···█···
  █·····█      █·····█      █······      ·██····      ···█···
  ██████·      ██████·      ██████·      ··████·      ···█···
  █······      █··█···      █······      ·····██      ···█···
  █······      █···█··      █······      █·····█      ···█···
  █······      █····█·      ███████      ·█████·      ···█···

  Also includes: B, U, O, N, L, C, colon ":", and digits 4-9
```

**Screen layouts by state:**

```
  State 0 (Menu):
  ┌──────────────────────────────────────────┐
  │                                          │
  │                                          │
  │         P R E S S   B U T T O N          │  ← 4× scale, y: 180-212
  │              T O   S T A R T             │  ← 4× scale, y: 230-262
  │                                          │
  │                                          │
  └──────────────────────────────────────────┘

  States 1-3 (Countdown):
  ┌──────────────────────────────────────────┐
  │                                          │
  │                                          │
  │                                          │
  │                  3                       │  ← 8× scale (64px tall)
  │               (or 2, 1)                  │     y: 208-272
  │                                          │
  │                                          │
  └──────────────────────────────────────────┘

  State 4 ("START"):
  ┌──────────────────────────────────────────┐
  │                                          │
  │                                          │
  │                                          │
  │             S T A R T                    │  ← 8× scale
  │                                          │     y: 208-272
  │                                          │
  └──────────────────────────────────────────┘

  State 6 (Result):
  ┌──────────────────────────────────────────┐
  │                                          │
  │           R E S U L T                    │  ← 8× scale, y: 120-184
  │                                          │
  │                                          │
  │          S C O R E :   1 5               │  ← 4× scale, y: 240-272
  │                                          │     (score = 15 shown)
  └──────────────────────────────────────────┘
```

**BCD score conversion for display:**
```
  player_score = 8'd15 (binary: 00001111)
  
  score_tens = (15 / 10) % 10 = 1  →  character "1" (0x31)
  score_ones = 15 % 10 = 5         →  character "5" (0x35)
  
  Display: "SCORE: 15"
  
  If score < 10: tens digit shows blank space " "
  Example: score = 7 → "SCORE:  7"
```

---

### 7.10 main_game_audio_processor — PWM Audio Engine

```
  ┌─ main_game_audio_processor ──────────────────────────────────────┐
  │                                                                   │
  │  current_game_state ──► ┌──────────────┐                         │
  │                         │ Track        │                         │
  │  beat_index ──────────► │ Sequencer    │──► melody_note_div      │
  │                         │ (case/case)  │──► sfx_note_div         │
  │  tempo_counter ───────► │              │──► drum_enable           │
  │                         └──────────────┘                         │
  │                                │            │           │        │
  │                                ▼            ▼           ▼        │
  │                         ┌──────────┐  ┌──────────┐  ┌───────┐   │
  │                         │note_gen  │  │note_gen  │  │ Drum  │   │
  │                         │(melody)  │  │(SFX)     │  │Channel│   │
  │                         └────┬─────┘  └────┬─────┘  └───┬───┘   │
  │                              │             │            │        │
  │                              ▼             ▼            ▼        │
  │                         ┌─────────────────────────────────┐      │
  │                         │   2-bit PWM DAC Mixer           │      │
  │                         │   audio_sum = mel + sfx + drum  │      │
  │                         │   pwm_out = (counter < sum)     │      │
  │                         └──────────────┬──────────────────┘      │
  │                                        │                         │
  │  Mute gate: OFF if sw=0 or HOLD ──────►AND──────► aud_pwm       │
  │                                                                   │
  │  aud_sd = 1 (amplifier always enabled)                            │
  └───────────────────────────────────────────────────────────────────┘
```

**Audio tracks by game state:**

```
  ┌────────────────────┬───────────────────────────────────────────────────┐
  │ Game State         │ What Plays                                       │
  ├────────────────────┼───────────────────────────────────────────────────┤
  │ HOLD (1)           │ Silence — all generators output 0                │
  ├────────────────────┼───────────────────────────────────────────────────┤
  │ INPUT/DISP (2-3)   │ Verse melody + drum rhythm                      │
  │                    │ 166ms per beat, 16-step loop:                    │
  │                    │                                                   │
  │                    │ Beat: 0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15│
  │                    │ Note: E4 E4 ·· E4 G4 G4 ·· G4 A4 A4 A4 C5 D5 C5 A4 G4│
  │                    │                                                   │
  │                    │ (·· = rest, 80% sound / 20% silence per beat)    │
  ├────────────────────┼───────────────────────────────────────────────────┤
  │ COUNTDOWN (4)      │ Short beep tick: 25ms burst of 1 kHz tone        │
  │                    │ (sfx_note_div = 50000 for first 25ms of beat)    │
  ├────────────────────┼───────────────────────────────────────────────────┤
  │ THROW/PULL/TURN    │ Build-up melody (Ode to Joy pattern), no drums   │
  │ (5-7)              │ 250ms per beat, 16-step loop:                    │
  │                    │                                                   │
  │                    │ Beat: 0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15│
  │                    │ Note: E5 E5 F5 G5 G5 F5 E5 D5 C5 C5 D5 E5 E5 D5 C5 A4│
  │                    │                                                   │
  │                    │ Tempo: slower (250ms vs 166ms) for dramatic build │
  ├────────────────────┼───────────────────────────────────────────────────┤
  │ RESULT (9)         │ Victory arpeggio — 4-note loop:                  │
  │                    │ C4 → E4 → G4 → C5 (repeat)                      │
  │                    │ 166ms per beat                                    │
  └────────────────────┴───────────────────────────────────────────────────┘
```

**Note frequency table (clock divisors at 100 MHz):**

```
  Note │ Frequency │ Divisor (100MHz / freq / 2)  │ Used In
  ─────┼───────────┼─────────────────────────────┼──────────────
  C4   │ 261.6 Hz  │ 191,110                     │ Victory
  E4   │ 329.6 Hz  │ 151,685                     │ Verse, Victory
  G4   │ 392.0 Hz  │ 127,551                     │ Verse, Victory
  A4   │ 440.0 Hz  │ 113,636                     │ Verse, Build-up
  C5   │ 523.3 Hz  │  95,556                     │ Verse, Build-up, Victory
  D5   │ 587.3 Hz  │  85,131                     │ Verse, Build-up
  E5   │ 659.3 Hz  │  75,844                     │ Build-up
  F5   │ 698.5 Hz  │  71,587                     │ Build-up
  G5   │ 784.0 Hz  │  63,775                     │ Build-up
  Tick │ ~1000 Hz  │  50,000                     │ Countdown beep
```

**Staccato gate effect:**
```
  Each beat step:
  ┌──────────────────────────────────┬────────┐
  │        SOUND ON (80%)            │MUTE 20%│
  │  tempo_counter < gate_limit      │ silent │
  └──────────────────────────────────┴────────┘
  ◄────────── tempo period ──────────────────►
  
  This creates a crisp, rhythmic articulation rather than
  a continuous drone.
```

---

### 7.11 note_generator — Square Wave Oscillator

```
  100 MHz clock
       │
       ▼
  ┌─────────────────────────────────────┐
  │  clk_counter counts up each cycle   │
  │                                     │
  │  When clk_counter >= note_div:      │
  │    audio_out = ~audio_out (toggle)  │
  │    clk_counter = 0                  │
  │                                     │
  │  When note_div = 0:                 │
  │    audio_out = 0 (silence)          │
  └─────────────────────────────────────┘
       │
       ▼
  Square wave at: freq = 100 MHz / (2 × note_div)
  
  Example: note_div = 113,636
           freq = 100,000,000 / (2 × 113,636) = 440.0 Hz = A4
```

---

### 7.12 scoring_design — Legacy Module (NOT USED)

This is an **earlier version** of the scoring system that is kept in the project but **not instantiated** by `master_game_top`.

**Differences from the active `action_fsm`:**

```
  ┌─────────────────────────┬────────────────────────────────┐
  │  scoring_design (old)   │  action_fsm (active)           │
  ├─────────────────────────┼────────────────────────────────┤
  │ Absolute thresholds     │ Self-calibrating baselines     │
  │ (board tilt = false +)  │ (tilt-immune, motion-only)     │
  ├─────────────────────────┼────────────────────────────────┤
  │ Per-phase cap: 10 pts   │ No per-phase cap               │
  │ Total max: 30 points    │ Unlimited accumulation         │
  ├─────────────────────────┼────────────────────────────────┤
  │ Rank system:            │ No rank — raw score only       │
  │  >24 = Excellent        │                                │
  │  ≥15 = Okay             │                                │
  │  <15 = Try Again        │                                │
  ├─────────────────────────┼────────────────────────────────┤
  │ Neutral-return debounce │ Rising-edge + cooldown timer   │
  │ (return to rest first)  │ (0.25 sec hardware debounce)   │
  ├─────────────────────────┼────────────────────────────────┤
  │ 7 states (incl. LOAD)   │ 6 states (LOAD removed)        │
  │ Async reset             │ Synchronous reset via sw       │
  └─────────────────────────┴────────────────────────────────┘
```

---

### 7.13 top — Legacy Top Module (NOT USED)

An earlier top-level that only wired the accelerometer + LEDs + 7-segment. No game logic, no VGA, no audio. Superseded by `master_game_top`.

---

## 8. Pin Constraints (ucf.xdc)

```
  ╔═══════════════════════════════════════════════════════════════════╗
  ║                    ACTIVE PIN ASSIGNMENTS                        ║
  ╠═══════════════════════╦════════╦══════════════════════════════════╣
  ║ Signal                ║ Pin    ║ Notes                           ║
  ╠═══════════════════════╬════════╬══════════════════════════════════╣
  ║ CLK100MHZ             ║ E3     ║ 100 MHz crystal osc             ║
  ║ sw (SW0)              ║ J15    ║ Start/reset switch              ║
  ║ reset_btn             ║ C12    ║ CPU Reset (active-low)          ║
  ╠═══════════════════════╬════════╬══════════════════════════════════╣
  ║ ACL_MISO              ║ E15    ║ Accelerometer SPI               ║
  ║ ACL_MOSI              ║ F14    ║                                 ║
  ║ ACL_SCLK              ║ F15    ║                                 ║
  ║ ACL_CSN               ║ D15    ║                                 ║
  ╠═══════════════════════╬════════╬══════════════════════════════════╣
  ║ vga_r[0..3]           ║ A3,B4, ║ VGA Red channel                 ║
  ║                       ║ C5,A4  ║                                 ║
  ║ vga_g[0..3]           ║ C6,A5, ║ VGA Green channel               ║
  ║                       ║ B6,A6  ║                                 ║
  ║ vga_b[0..3]           ║ B7,C7, ║ VGA Blue channel                ║
  ║                       ║ D7,D8  ║                                 ║
  ║ vga_hsync             ║ B11    ║ Horizontal sync                 ║
  ║ vga_vsync             ║ B12    ║ Vertical sync                   ║
  ╠═══════════════════════╬════════╬══════════════════════════════════╣
  ║ LED[0..14]            ║ H17,   ║ 15 LEDs = raw accel data        ║
  ║                       ║ K15,...║                                 ║
  ║                       ║ V12    ║                                 ║
  ╠═══════════════════════╬════════╬══════════════════════════════════╣
  ║ SEG[0..6]             ║ L18,   ║ 7-segment cathodes (cg..ca)     ║
  ║                       ║ T11,...║                                 ║
  ║                       ║ T10    ║                                 ║
  ║ DP                    ║ H15    ║ Decimal point                   ║
  ║ AN[0..7]              ║ J17,   ║ 7-segment anodes                ║
  ║                       ║ J18,...║                                 ║
  ║                       ║ U13    ║                                 ║
  ╠═══════════════════════╬════════╬══════════════════════════════════╣
  ║ AUD_PWM               ║ A11    ║ Audio PWM output                ║
  ║ AUD_SD                ║ D12    ║ Audio amp shutdown (held high)  ║
  ╚═══════════════════════╩════════╩══════════════════════════════════╝
  
  All pins: LVCMOS33 (3.3V logic)
```

---

## 9. Module Interconnect Map

```
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                      SIGNAL FLOW BETWEEN MODULES                       │
  │                                                                         │
  │   iclk_gen ──── clk_4MHz ────► spi_master                              │
  │                                     │                                   │
  │                              acl_data[14:0]                             │
  │                    ┌────────────────┼───────────────┐                   │
  │                    │                │               │                   │
  │                    ▼                ▼               ▼                   │
  │              action_fsm        VGA_TEST         LED[14:0]              │
  │                    │                │                                   │
  │    ┌───────────────┼────────┐       │                                   │
  │    │               │        │       │                                   │
  │    ▼               ▼        ▼       │                                   │
  │  final_marks   timer_sec  state_out │                                   │
  │  [7:0]         [3:0]      [2:0]     │                                   │
  │    │               │        │       │                                   │
  │    │    ┌──────────┘        │       │                                   │
  │    │    │                   │       │                                   │
  │    ▼    ▼                   │       │                                   │
  │  seg7_control               │       │                                   │
  │    │                        │       │                                   │
  │    ▼                        │       ├──► VGA ──► hsync, vsync,          │
  │  SEG, DP, AN                │       │            video_on, x_pos, y_pos │
  │                             │       │                                   │
  │    ┌── audio_state_mapped ──┘       ├──► IMAGE_ROM (×9) ──► game_color │
  │    │   (combinational remap)        │                                   │
  │    ▼                                ├──► UI_TEXT_ENGINE ──► text_pixel  │
  │  main_game_audio_processor          │                                   │
  │    │                                └──► final_vga_color ──► vga_r/g/b │
  │    ▼                                                                    │
  │  AUD_PWM, AUD_SD                                                       │
  │                                                                         │
  │  player_score ── action_fsm.final_marks ──► VGA_TEST ──► UI_TEXT_ENGINE │
  │  (score displayed on both 7-seg AND VGA result screen)                  │
  └─────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Clock Domain Map

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                        CLOCK DOMAINS                             │
  │                                                                  │
  │  100 MHz (CLK100MHZ) ─── Primary domain ──────────────────────  │
  │    │                                                             │
  │    ├── action_fsm         (all sequential logic)                 │
  │    ├── seg7_control       (anode refresh counter)                │
  │    ├── VGA                (pixel counter, clk_div)               │
  │    ├── VGA_TEST           (state machine, animation counter)     │
  │    ├── main_game_audio    (tempo counter, PWM counter)           │
  │    ├── note_generator ×2  (frequency dividers)                   │
  │    └── iclk_gen           (divider to produce 4 MHz)             │
  │                                                                  │
  │  4 MHz (clk_4MHz / iclk) ─── SPI domain ─────────────────────  │
  │    │                                                             │
  │    └── spi_master         (SPI state machine, bit-bang)          │
  │         │                                                        │
  │         └── 1 MHz SCLK    (derived internally by div-2)          │
  │                                                                  │
  │  25 MHz (pixel_tick) ─── Internal to VGA module ──────────────  │
  │    │                                                             │
  │    └── Pixel counter      (h_count, v_count advance)             │
  │                                                                  │
  │  Domain crossing:                                                │
  │    spi_master latches acl_data on negedge of 4 MHz               │
  │    action_fsm reads acl_data on posedge of 100 MHz               │
  │    (Acceptable: acl_data changes at ~100 Hz, sampled at 100 MHz) │
  └──────────────────────────────────────────────────────────────────┘
```

---

## 11. Building and Programming

```
  Step 1: Open Project
  ┌─────────────────────────────────────────────┐
  │  Vivado 2024.1+ → File → Open Project      │
  │  → KKEE2163_Digital_Electronics_Project.xpr │
  └─────────────────────────────────────────────┘
           │
           ▼
  Step 2: Verify Top Module
  ┌─────────────────────────────────────────────┐
  │  Sources panel → master_game_top should be  │
  │  marked as the top module (bold, with icon) │
  │                                             │
  │  If not: right-click → Set as Top           │
  └─────────────────────────────────────────────┘
           │
           ▼
  Step 3: Synthesis → Implementation → Bitstream
  ┌─────────────────────────────────────────────┐
  │  Flow Navigator:                            │
  │    Run Synthesis ──► Run Implementation      │
  │    ──► Generate Bitstream                    │
  │                                             │
  │  (Takes 5-15 minutes depending on machine)  │
  └─────────────────────────────────────────────┘
           │
           ▼
  Step 4: Program the FPGA
  ┌─────────────────────────────────────────────┐
  │  Connect Nexys A7 via USB                   │
  │  Hardware Manager → Open Target → Auto      │
  │  Program Device → Select .bit file          │
  └─────────────────────────────────────────────┘
           │
           ▼
  Step 5: Connect Peripherals
  ┌─────────────────────────────────────────────┐
  │  ● VGA cable → monitor (required for game)  │
  │  ● Speakers → audio jack (optional)         │
  │  ● Nothing else needed — accel is on-board  │
  └─────────────────────────────────────────────┘
           │
           ▼
  Step 6: Play!
  ┌─────────────────────────────────────────────┐
  │  ● Flip SW0 UP to start                    │
  │  ● Hold board still during countdown (4s)  │
  │  ● Perform gestures during each phase (8s) │
  │  ● View final score on monitor + 7-seg     │
  │  ● Flip SW0 DOWN to reset                  │
  └─────────────────────────────────────────────┘
```

---

## 12. Resource Usage Summary

```
  Module               │ Key Resources Used
  ─────────────────────┼──────────────────────────────────────
  IMAGE_ROM (×9)       │ 9 × 19,200 × 12-bit = ~2.1 Mbit BRAM
  spi_master           │ 93-state FSM + 32-bit counter
  action_fsm           │ 6-state FSM + baseline trackers + edge detectors
  VGA                  │ 10-bit H/V counters + 2-bit clock divider
  VGA_TEST             │ 7-state FSM + animation MUX + composition logic
  UI_TEXT_ENGINE        │ ~20 character font ROM (8×8 each) + coordinate math
  seg7_control         │ 8:1 anode MUX + BCD decoder + 17-bit refresh counter
  main_game_audio      │ 2× note_generators + tempo sequencer + PWM mixer
  iclk_gen             │ 5-bit counter + toggle register
  
  Target FPGA: XC7A100T
  ● 15,850 slices / 101,440 LUTs / 4,860 Kbit BRAM available
  ● This design uses a small fraction of available resources
  ● The 9 IMAGE_ROMs are the largest consumers (BRAM)
```
