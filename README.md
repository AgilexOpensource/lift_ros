# lift_ros

[中文](README.zh-CN.md)

ROS 2 driver for the lift column (arm protocol) and waist pitch (RB200 protocol) with profile position control, built on [agx_motor_sdk](https://github.com/kehuanjack/agx_motor_sdk).

> **Safety:** Default startup configures and enables the motors and accepts commands. Check wiring, node IDs, calibration, limits and mechanical clearance first, and provide an independent emergency stop. Provide mechanical load support for the column.

## Requirements

Tested on Ubuntu 22.04 with ROS 2 Humble.

## Install

The SDK compiles a C++ extension during install, so install the build tools first:

```bash
sudo apt install build-essential cmake libasio-dev libyaml-cpp-dev python3-dev
mkdir -p ~/lift_ws/src && cd ~/lift_ws
git clone https://github.com/AgilexOpensource/lift_ros.git src/lift_ros
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src -r -y
```

Install the SDK with system pip and build:

```bash
pip3 install git+https://github.com/kehuanjack/agx_motor_sdk.git
colcon build --packages-select lift_ros
source install/setup.bash
```

Or, recommended to keep the system Python clean, a virtual environment that still sees the ROS Python packages:

```bash
python3 -m venv --system-site-packages ~/lift_ws/.venv
source ~/lift_ws/.venv/bin/activate
pip install git+https://github.com/kehuanjack/agx_motor_sdk.git
python3 -m colcon build --packages-select lift_ros
source install/setup.bash
```

Activate the venv in every new terminal before `source install/setup.bash`. `python3 -m colcon` makes the node use the venv Python; plain `colcon` would use the system Python, which cannot import `agx_motor_sdk` from the venv.

## Quick start

Bring up `can0` at 1 Mbit/s and launch the driver. Run `ip link set` only while the interface is down and unused.

```bash
sudo ip link set can0 up type can bitrate 1000000
ros2 launch lift_ros lift.launch.py
```

The node is `/lift/lift_node` with joints `torso_joint1` (column) and `torso_joint2` (waist pitch), both on `can0`. To check the connection without configuring, enabling or accepting commands:

```bash
ros2 launch lift_ros lift.launch.py \
  auto_configure:=false auto_enable:=false control_enabled:=false
```

In another terminal, read feedback and send a position target. **Commands move the joints.**

```bash
ros2 topic echo /lift/feedback/joint_states
ros2 topic echo /lift/feedback/motor_status
ros2 topic pub --once /lift/control/joint_states sensor_msgs/msg/JointState \
  "{name: ['torso_joint1'], position: [0.0]}"
```

Close the command gate, then disable the motors:

```bash
ros2 service call /lift/control_enable std_srvs/srv/SetBool '{data: false}'
ros2 service call /lift/enable std_srvs/srv/SetBool '{data: false}'
```

## Interfaces

Names are relative to the node namespace (default `/lift`). Topics use reliable, volatile QoS with depth 10.

| Name | Kind | Type | Description |
|---|---|---|---|
| `control/joint_states` | Subscribed topic | `sensor_msgs/msg/JointState` | Joint targets |
| `feedback/joint_states` | Published topic | `sensor_msgs/msg/JointState` | Joint feedback at `feedback_rate` |
| `feedback/motor_status` | Published topic | `diagnostic_msgs/msg/DiagnosticArray` | One status per joint at `status_rate` |
| `enable` | Service | `std_srvs/srv/SetBool` | Enable or disable the motors |
| `control_enable` | Service | `std_srvs/srv/SetBool` | Open or close the command gate |

Command rules:

- `name` and `position` must be nonempty, the same length and free of duplicates. Subsets are allowed; unknown joints are skipped.
- Used values must be finite; an invalid message is rejected as a whole. A failed write is logged and other joints continue.
- Only `position` is used. The first target for each joint also selects profile position mode; later targets leave the mode unchanged. Disabling through the `enable` service resets this.
- Headers are ignored; there is no age check or acknowledgment.

Units: the column uses m and m/s in ROS (`0.1` m is 100 mm) and reports PWM (±450) as effort, which is not a measured force. The waist uses rad, rad/s and N·m.

Joints without SDK state are left out of `feedback/joint_states`. The `motor_status` fields are listed in [docs/reference.md](docs/reference.md#diagnostics).

## Configuration

- [config/lift.yaml](config/lift.yaml): hardware module `torso` with `torso_joint1` (column, ID 1, 0 to 0.4 m) and `torso_joint2` (waist pitch, ID 2), polarity, limits and profile. See the [SDK YAML reference](https://github.com/kehuanjack/agx_motor_sdk/blob/main/YAML_CONFIG.md).
- [config/lift_ros.yaml](config/lift_ros.yaml): node parameters, listed in [docs/reference.md](docs/reference.md#ros-parameters).

Launch arguments (empty keeps the value from `params_file`):

| Argument | Default | Description |
|---|---|---|
| `namespace` | `lift` | Node namespace |
| `params_file` | `config/lift_ros.yaml` | Node parameter file |
| `yaml_path` | empty | Hardware YAML path |
| `module_key` | empty | Top-level YAML module |
| `can_channel` | empty | CAN interface override |
| `control_enabled` | empty | Initial command gate, `true` or `false` |
| `auto_configure`, `auto_enable` | empty | Configure and enable at startup, `true` or `false` |
| `feedback_rate`, `status_rate` | empty | Publish rates, Hz |
| `status_timeout` | empty | Diagnostics freshness bound, s |

`ros2 launch lift_ros lift.launch.py --show-args` lists them. Hardware YAML lookup and operating boundaries are in [docs/reference.md](docs/reference.md).

## Troubleshooting

- `GitHub release metadata request failed` while installing `agx_motor_sdk`: the SDK downloads protocol libraries from GitHub, and anonymous access allows 60 API requests per hour per IP. Wait for the limit to reset, or set `GITHUB_TOKEN` to a GitHub token and install again.
- `No module named 'agx_motor_sdk'`: activate the venv and rebuild with `python3 -m colcon build`.
- `failed to open CAN: can0`: bring the interface up as in [Quick start](#quick-start) and check `ip -brief link show`.
- `lift YAML not found`: pass an absolute `yaml_path`, or a file name installed under `share/lift_ros/config`.
- `lift configure failed` or `lift enable failed`: check power, wiring and node IDs, then run the connection check.
- Log says `External control gate is closed`: call `control_enable` with `{data: true}`.
- Log says `set_target failed for torso_joint1`: check power, CAN and the enable state of that joint.
- Log says `control/joint_states ignored`: fix the message as described in the command rules.
- `motor_status` entries are `STALE`: no fresh feedback within `status_timeout`; check power and CAN.

## License

Apache-2.0, see [LICENSE](LICENSE).
