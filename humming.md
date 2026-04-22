# Multiroom Audio Debugging - Wondom GAB8 Setup

## Overview
This document summarizes debugging of a multiroom audio system based on Wondom GAB8 amplifiers.

## Hardware Setup
- 3x Wondom GAB8 (TPA3244 Class-D amplifiers)
- Raspberry Pi 5 (audio source)
- Meanwell 24V ~400W power supply
- Speaker wiring:
  - ~20m length
  - 2-core, unshielded
  - runs parallel to mains wiring inside walls

## Observed Issues
### 1. Initial symptom: low-frequency hum
- Present even without audio input
- Independent of Raspberry / USB

### 2. Later symptom: "radio-like noise"
- Sounds like interference/static
- Changes depending on wiring layout
- Appears in different rooms at different times

### 3. Loud pop during power-on
- Sharp transient on startup
- Potentially damaging to speakers

### 4. Inconsistent behavior
- Not tied to specific room
- Moves when channels are reassigned

## Diagnosis
Root cause (high probability):
EMI / HF interference via speaker cables + poor internal wiring layout

## Key Insight
Wall wiring makes the system sensitive.
Internal wiring determines whether the noise is audible.

## Recommended Fixes
1. Clean up internal wiring layout  
2. Pair and route speaker cables properly  
3. Insulate all exposed connections  
4. Add ferrite cores at amp outputs  
5. Implement SHDN control  

## Conclusion
This is not a hardware defect.
This is a classic EMI + layout issue: long cables + Class-D amplification + poor wiring geometry.
