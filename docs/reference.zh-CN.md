# lift_ros 参考

[English](reference.md)

`lift_node` 的参数、启动参数、指令规则、硬件 YAML、诊断、运行边界和常见问题。入门请先看 [README](../README.zh-CN.md)。

## ROS 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `yaml_path` | 空 | 硬件 YAML；[lift_ros.yaml](../config/lift_ros.yaml) 设为 `lift.yaml` |
| `module_key` | 空 | YAML 顶层模块名；[lift_ros.yaml](../config/lift_ros.yaml) 设为 `torso` |
| `can_channel` | 空 | 覆盖 CAN 接口；[lift_ros.yaml](../config/lift_ros.yaml) 设为 `can0` |
| `auto_configure` | `true` | 启动时配置关节组 |
| `auto_enable` | `true` | 启动时使能电机 |
| `control_enabled` | `true` | 初始指令门控 |
| `feedback_rate` | `100.0` | 关节反馈频率，Hz |
| `status_rate` | `30.0` | 诊断发布频率，Hz；不改变硬件反馈频率 |
| `status_timeout` | `2.0` | 诊断新鲜度上限，s |
| `feedback_timeout` | `0.5` | 关节反馈超过此时长不再发布，s；0 表示一直发布缓存值 |
| `velocity_joints` | `[""]` | 由[速度环](#速度环)代替轮廓位置模式驱动的 arm 协议关节；空字符串忽略 |
| `velocity_rate` | `100.0` | 速度环频率，Hz |
| `velocity_gain` | `3.0` | 速度环位置增益，1/s |
| `velocity_tolerance` | `0.0003` | 速度环目标附近的死区，关节单位 |

- 频率和 `status_timeout` 必须有限且大于 0；`feedback_timeout`、`velocity_gain` 和 `velocity_tolerance` 必须有限且不小于 0。
- 所有参数在启动后只读。
- `control_enabled` 保持启动值；`control_enable` 服务修改实际门控。
- 逐关节使能和失能帧之间间隔 0.1 s。

## 启动参数

`lift.launch.py` 为上表中每个参数提供同名启动参数，另有：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `namespace` | `lift` | 节点命名空间 |
| `params_file` | `config/lift_ros.yaml` | 节点参数文件 |

- 参数类启动参数默认为空，留空则使用 `params_file` 中的值。
- `control_enabled`、`auto_configure` 和 `auto_enable` 取 `true` 或 `false`。

## 指令与反馈

`control/joint_states` 消息的规则：

- `name` 和 `position` 必须非空、长度相同且无重复。可以只发部分关节；未知关节会被跳过。
- 用到的值必须有限；无效消息整条拒绝。单个关节写入失败会记录日志，其他关节继续执行。
- 只使用 `position`。arm 协议关节每帧都带轮廓位置模式。RB200 关节的第一个目标选择轮廓位置模式，后续目标不改变模式；通过 `enable` 服务失能后会重置这一状态。`velocity_joints` 中的关节由[速度环](#速度环)处理。
- 忽略消息头；不检查时效，也没有应答。

单位：升降柱在 ROS 中使用 m 和 m/s（`0.1` m 即 100 mm），effort 反馈的是 PWM（±450），不是实测力。腰部使用 rad、rad/s 和 N·m。

没有 SDK 状态的关节不出现在 `feedback/joint_states` 中。高速反馈超过 `feedback_timeout`（按主机挂钟时间）的关节也不发布：电机断电后 SDK 会一直返回最后一个样本，否则下游控制器会把它当成实时反馈。没有时间戳的样本无法判断，照常发布。

## 速度环

轮廓位置模式下，升降柱固件把每个新目标都规划到停止，因此连续缓慢变化的目标会一顿一顿。`velocity_joints` 中的关节改由节点内的位置环以速度模式驱动；话题仍然收发位置目标。

- 目标先按 YAML 限位截断。参考位置以关节的 `profile_vel` 和 `profile_accel` 向目标移动（不使用 `profile_decel`）。
- 节点以 `velocity_rate` 发送参考速度加上 `velocity_gain` 乘以误差，误差为延迟 0.3 s（实测电机滞后）的参考位置与反馈位置之差。距目标 `velocity_tolerance` 以内不再纠偏，关节以速度 0 保持在目标处。
- 指令速度限制在 `profile_vel` 以内，会越过限位时置 0。
- 每个速度帧都带 0.1 s 固件超时，节点停止发送后电机会自行停下。
- 关闭指令门控、通过 `enable` 失能、反馈过期或被扣留、电机未使能时，发送速度 0 并停止速度环。下一个目标从实测位置重新开始。
- 只支持 arm 协议关节。关节未知、协议不符或缺少 `profile_vel`、`profile_accel` 时启动失败。

## 硬件 YAML

- 相对的 `yaml_path` 在安装后的 `share/lift_ros/config` 下查找。其他文件请用绝对路径；不支持 `package://` URL。
- `yaml_path` 为空时依次使用环境变量 `LIFT_ROS_CONFIG` 和 `lift.yaml`。
- `module_key` 为空时用文件名主干，但 `lift.yaml` 对应模块 `torso`。
- `can_channel` 会替换模块默认接口，以及所有与之相同的关节接口。

字段含义见 [SDK YAML 参考](https://github.com/kehuanjack/agx_motor_sdk/blob/main/YAML_CONFIG.md)。在 [lift.yaml](../config/lift.yaml) 中，升降柱用 `polarity: 0.001` 把关节 m 换算为电机 mm，其运动曲线单位为 mm/s 和 mm/s²。本驱动不应用 `torque_limit`。

## 诊断

`feedback/motor_status` 每次发布一个 `DiagnosticArray`，每个关节一条 `DiagnosticStatus`。`name` 为关节名，`hardware_id` 为 `<can_channel>:<node_id>`，所有值均为字符串。`control_mode` 固定为 `pos`。

升降柱（`torso_joint1`，arm 协议）：

| 键 | 说明 |
|---|---|
| `enabled` | 硬件使能位 |
| `undervoltage`, `motor_overtemp`, `driver_overcurrent`, `driver_overtemp` | 故障位 |
| `collision_tripped`, `driver_error`, `stall_tripped` | 保护和错误位 |
| `bus_voltage_v`, `bus_current` | 母线电压（V）和母线电流 |
| `driver_temp_deg`, `motor_temp_deg` | 温度，°C |
| `status_raw` | 固件原始状态字节，十进制 |

任一故障或保护位置位时为 `ERROR`，消息中列出这些位；否则为 `OK`，消息为 `enabled` 或 `disabled`。

腰部俯仰（`torso_joint2`，RB200 协议，CiA 402 状态字）：

| 键 | 说明 |
|---|---|
| `enabled` | 是否处于 `operation_enabled` 状态 |
| `cia402_state` | 驱动器状态，如 `switch_on_disabled`、`operation_enabled` 或 `fault` |
| `ready_to_switch_on`, `switched_on`, `fault`, `voltage_enabled`, `switch_on_disabled` | 状态字第 0、1、3、4、6 位 |
| `warning`, `remote`, `target_reached`, `internal_limit_active`, `homing_complete` | 状态字第 7、9、10、11、15 位 |
| `quick_stop_active` | 驱动器处于快速停止状态 |
| `error_code`, `status_word` | 十六进制，如 `0x0000` |

`fault` 位置位时为 `ERROR`，消息为 `<state>, error_code 0x....`；`warning` 位置位时为 `WARN`；否则为 `OK`，消息为驱动器状态。

两种协议下，时间戳缺失、非正、在未来或已过期时均为 `STALE`，值为 `unknown`。新鲜指按主机挂钟时间 `0 <= age <= status_timeout`。

## 运行边界

- 关闭指令门控不会失能电机，也不会取消已发送的目标；速度环关节会被停止。
- 诊断过期不会停止指令。关节反馈另有 `feedback_timeout`。
- 节点退出时关闭 SDK 连接，但不失能电机；此时升降柱依靠机械承重支撑。
- `enable` 服务返回 SDK 的结果；硬件实际状态请看 `motor_status`。
- 看门狗、轨迹执行和故障恢复应由本驱动的上层负责。

## 常见问题

- `lift YAML not found`：传入绝对路径的 `yaml_path`，或安装在 `share/lift_ros/config` 下的文件名。
- `lift configure failed` 或 `lift enable failed`：检查供电、接线和节点 ID，再运行[连接检查](../README.zh-CN.md#快速开始)。
- 日志显示 `set_target failed for torso_joint1`：检查该关节的供电、CAN 和使能状态。
- 日志显示 `control/joint_states ignored`：按[指令与反馈](#指令与反馈)中的规则修正消息。
- `motor_status` 条目为 `STALE`：`status_timeout` 内没有新的反馈；检查供电和 CAN。
