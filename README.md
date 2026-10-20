# lift_ros

ROS 2 support for the lift column and waist pitch, reusing `motor_ros`.

See [motor_ros](https://github.com/AgilexOpensource/motor_ros#readme) for
prerequisites, controls, feedback, parameters, and safety precautions.
This page covers lift-specific setup and units. Provide mechanical load support.

## Installation

Follow the motor_ros installation guide, then add this package to that workspace:

```bash
cd ~/motor_ws
git clone https://github.com/AgilexOpensource/lift_ros.git src/lift_ros
colcon build --packages-up-to lift_ros
source install/setup.bash
```

## Quick Start

Both joints share `can0` at 1 Mbit/s. Activate it with the interface down;
do not reconfigure an adapter in use.

```bash
sudo ip link set can0 up type can bitrate 1000000
```

Start with the reviewed configuration:

```bash
ros2 launch lift_ros lift.launch.py
```

Use `/lift` instead of `/motor` in the motor_ros topic and service examples,
with joint names `torso_joint1` and `torso_joint2`.

## Lift Differences

**Use `pos` mode; the column does not support MIT.** The motor_ros rotary-joint
units and MIT examples do not apply to the column.

- Column position/velocity: m and m/s; `0.1 m` means `100 mm`.
- Column profile speed/acceleration: mm/s and mm/s^2.
- Column `effort`: scaled PWM, not measured force or torque; do not use for force control.
- Waist position/velocity/effort: rad, rad/s, and N*m.

## Configuration

- [lift.yaml](config/lift.yaml): module `torso`, joints, IDs, polarity, limits,
  and profile settings. Default column range: 0.0 to 0.4 m.
- [lift_ros.yaml](config/lift_ros.yaml): startup settings; default mode is `pos`.

Both joints are enabled in the example, with IDs 1 and 2. To change the CAN
interface, update any explicit per-joint `can_channel` fields too.

## License

Apache-2.0; see `LICENSE`.
