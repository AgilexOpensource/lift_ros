# lift_ros

[English](README.md)

升降柱（arm 协议）和腰部俯仰（RB200 协议）的 ROS 2 驱动，使用轮廓位置控制，基于 [agx_motor_sdk](https://github.com/kehuanjack/agx_motor_sdk)。

> **Safety:** 默认启动会配置并使能电机，并接受控制指令。启动前请检查接线、节点 ID、标定、限位和机械空间，并准备独立的急停装置。请为升降柱提供机械承重支撑。

## 环境要求

已在 Ubuntu 22.04 + ROS 2 Humble 上测试。

## 安装

SDK 安装时会编译 C++ 扩展，需先安装构建工具及 Python 和 ROS 工具。`rosdep init` 仅在本机从未执行过时运行：

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

用系统 pip 安装 SDK 并构建：

```bash
pip3 install git+https://github.com/kehuanjack/agx_motor_sdk.git
colcon build --packages-select lift_ros
source install/setup.bash
```

或者，推荐使用虚拟环境，避免改动系统 Python。该虚拟环境仍可访问 ROS 的 Python 包：

```bash
python3 -m venv --system-site-packages ~/lift_ws/.venv
source ~/lift_ws/.venv/bin/activate
pip install git+https://github.com/kehuanjack/agx_motor_sdk.git
python3 -m colcon build --packages-select lift_ros
source install/setup.bash
```

每个新终端都要先激活虚拟环境，再执行 `source install/setup.bash`。`python3 -m colcon` 让节点使用虚拟环境中的 Python；直接用 `colcon` 会使用系统 Python，无法导入虚拟环境中的 `agx_motor_sdk`。

## 快速开始

以 1 Mbit/s 启用 `can0` 并启动驱动。仅在接口处于关闭状态且未被其他程序使用时执行 `ip link set`。

```bash
sudo ip link set can0 up type can bitrate 1000000
ros2 launch lift_ros lift.launch.py
```

节点为 `/lift/lift_node`，关节为 `torso_joint1`（升降柱）和 `torso_joint2`（腰部俯仰），均在 `can0` 上。只检查连接、不配置、不使能、不接受指令：

```bash
ros2 launch lift_ros lift.launch.py \
  auto_configure:=false auto_enable:=false control_enabled:=false
```

在另一个终端读取反馈并发送位置目标。**指令会让关节运动。**

```bash
ros2 topic echo --once /lift/feedback/joint_states
ros2 topic echo --once /lift/feedback/motor_status
ros2 topic pub --once /lift/control/joint_states sensor_msgs/msg/JointState \
  "{name: ['torso_joint1'], position: [0.0]}"
```

关闭指令门控，再失能电机：

```bash
ros2 service call /lift/control_enable std_srvs/srv/SetBool '{data: false}'
ros2 service call /lift/enable std_srvs/srv/SetBool '{data: false}'
```

## 接口

名称相对于节点命名空间（默认 `/lift`）。话题使用 reliable、volatile QoS，深度 10。

| 名称 | 类别 | 类型 | 说明 |
|---|---|---|---|
| `control/joint_states` | 订阅话题 | `sensor_msgs/msg/JointState` | 关节目标 |
| `feedback/joint_states` | 发布话题 | `sensor_msgs/msg/JointState` | 按 `feedback_rate` 发布的关节反馈 |
| `feedback/motor_status` | 发布话题 | `diagnostic_msgs/msg/DiagnosticArray` | 按 `status_rate` 发布，每关节一条状态 |
| `enable` | 服务 | `std_srvs/srv/SetBool` | 使能或失能电机 |
| `control_enable` | 服务 | `std_srvs/srv/SetBool` | 打开或关闭指令门控 |

指令规则和单位见 [docs/reference.zh-CN.md](docs/reference.zh-CN.md#指令与反馈)；`motor_status` 字段见 [docs/reference.zh-CN.md](docs/reference.zh-CN.md#诊断)。

## 配置

- [config/lift.yaml](config/lift.yaml)：硬件模块 `torso`，包含 `torso_joint1`（升降柱，ID 1，0 到 0.4 m）和 `torso_joint2`（腰部俯仰，ID 2）、极性、限位和运动曲线。字段见 [SDK YAML 参考](https://github.com/kehuanjack/agx_motor_sdk/blob/main/YAML_CONFIG.md)。
- [config/lift_ros.yaml](config/lift_ros.yaml)：节点参数，见 [docs/reference.zh-CN.md](docs/reference.zh-CN.md#ros-参数)。

常用启动参数（留空则使用 `params_file` 中的值）：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `can_channel` | 空 | 覆盖 CAN 接口 |
| `control_enabled` | 空 | 初始指令门控，`true` 或 `false` |
| `auto_configure`, `auto_enable` | 空 | 启动时配置和使能，`true` 或 `false` |

`ros2 launch lift_ros lift.launch.py --show-args` 可列出全部参数。完整的参数和启动参数列表、硬件 YAML 查找和运行边界见 [docs/reference.zh-CN.md](docs/reference.zh-CN.md)。

## 常见问题

- 安装 `agx_motor_sdk` 时报 `GitHub release metadata request failed`：SDK 安装时会从 GitHub 下载协议库，匿名访问每个 IP 每小时只能请求 60 次 API。等限额重置，或把 `GITHUB_TOKEN` 设为 GitHub token 后重装。
- `No module named 'agx_motor_sdk'`：激活虚拟环境，并用 `python3 -m colcon build` 重新构建。
- `failed to open CAN: can0`：按[快速开始](#快速开始)启用接口，并用 `ip -brief link show` 检查。
- 日志显示 `External control gate is closed`：调用 `control_enable`，参数为 `{data: true}`。

其他问题见 [docs/reference.zh-CN.md](docs/reference.zh-CN.md#常见问题)。

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。
