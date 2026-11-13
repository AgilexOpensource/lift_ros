# lift_ros

[中文](README.zh-CN.md)

ROS 2 driver for the lift column (arm protocol) and waist pitch (RB200 protocol) with profile position control, built on [agx_motor_sdk](https://github.com/kehuanjack/agx_motor_sdk).

> **Safety:** Default startup configures and enables the motors and accepts commands. Check wiring, node IDs, calibration, limits and mechanical clearance first, and provide an independent emergency stop. Provide mechanical load support for the column.

## Requirements

Tested on Ubuntu 22.04 with ROS 2 Humble.

## Install

The SDK compiles a C++ extension during install, so install the build tools and Python and ROS tooling first. `rosdep init` runs only on a machine where it has never run:

```bash
sudo apt install build-essential cmake libasio-dev libyaml-cpp-dev python3-dev \
  python3-pip python3-venv python3-colcon-common-extensions python3-rosdep
[ -f /etc/ros/rosdep/sources.list.d/20-default.list ] || sudo rosdep init
rosdep update
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
ros2 topic echo --once /lift/feedback/joint_states
ros2 topic echo --once /lift/feedback/motor_status
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

Command rules and units are in [docs/reference.md](docs/reference.md#commands-and-feedback); the `motor_status` fields are in [docs/reference.md](docs/reference.md#diagnostics).

## Configuration

- [config/lift.yaml](config/lift.yaml): hardware module `torso` with `torso_joint1` (column, ID 1, 0 to 0.4 m) and `torso_joint2` (waist pitch, ID 2), polarity, limits and profile. See the [SDK YAML reference](https://github.com/kehuanjack/agx_motor_sdk/blob/main/YAML_CONFIG.md).
- [config/lift_ros.yaml](config/lift_ros.yaml): node parameters, listed in [docs/reference.md](docs/reference.md#ros-parameters).

Common launch arguments (empty keeps the value from `params_file`):

| Argument | Default | Description |
|---|---|---|
| `can_channel` | empty | CAN interface override |
| `control_enabled` | empty | Initial command gate, `true` or `false` |
| `auto_configure`, `auto_enable` | empty | Configure and enable at startup, `true` or `false` |

`ros2 launch lift_ros lift.launch.py --show-args` lists all arguments. The full parameter and launch argument lists, hardware YAML lookup and operating boundaries are in [docs/reference.md](docs/reference.md).

## Troubleshooting

- `GitHub release metadata request failed` while installing `agx_motor_sdk`: the SDK downloads protocol libraries from GitHub, and anonymous access allows 60 API requests per hour per IP. Wait for the limit to reset, or set `GITHUB_TOKEN` to a GitHub token and install again.
- `No module named 'agx_motor_sdk'`: activate the venv and rebuild with `python3 -m colcon build`.
- `failed to open CAN: can0`: bring the interface up as in [Quick start](#quick-start) and check `ip -brief link show`.
- Log says `External control gate is closed`: call `control_enable` with `{data: true}`.

Other symptoms are in [docs/reference.md](docs/reference.md#troubleshooting).

## License

Apache-2.0, see [LICENSE](LICENSE).
