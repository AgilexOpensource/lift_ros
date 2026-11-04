# lift_ros

ROS 2 driver for the lift column (arm protocol) and waist pitch (RB200) with
profile position control.

> **Safety:** Default startup configures and enables the motors and accepts
> commands. Check wiring, node IDs, calibration, limits and mechanical clearance
> first, and provide an independent emergency stop.
> Provide mechanical load support for the column.

## Installation

Use a terminal with your ROS 2 environment active, colcon, and Python pip.

```bash
python3 -m pip install git+https://github.com/kehuanjack/agx_motor_sdk.git
mkdir -p ~/lift_ws/src
cd ~/lift_ws
git clone https://github.com/AgilexOpensource/lift_ros.git src/lift_ros
colcon build --packages-select lift_ros
source install/setup.bash
```

## Launch

The default configuration uses `can0` at 1 Mbit/s. Activate it with the
interface down; do not reconfigure an adapter in use.

```bash
sudo ip link set can0 up type can bitrate 1000000
ros2 launch lift_ros lift.launch.py
```

The node is `/lift/lift_node` with joints `torso_joint1` (column) and `torso_joint2` (waist pitch); both share `can0`. For a connection check
without configure, enable or external commands:

```bash
ros2 launch lift_ros lift.launch.py \
  auto_configure:=false auto_enable:=false control_enabled:=false
```

## Control and Feedback

Run commands in another terminal with ROS 2 and the workspace loaded.
**Commands can move the joints.** The examples command `torso_joint1` to 0.

```bash
ros2 topic echo /lift/feedback/joint_states
ros2 topic echo /lift/feedback/motor_status
ros2 topic pub --once /lift/control/joint_states sensor_msgs/msg/JointState \
  "{name: ['torso_joint1'], position: [0.0]}"
```

`enable` switches motor enable; `control_enable` opens or closes the software
command gate:

```bash
ros2 service call /lift/enable std_srvs/srv/SetBool '{data: true}'
ros2 service call /lift/control_enable std_srvs/srv/SetBool '{data: true}'
ros2 service call /lift/control_enable std_srvs/srv/SetBool '{data: false}'
ros2 service call /lift/enable std_srvs/srv/SetBool '{data: false}'
```

Names below are relative to the namespace (default `/lift`). Topics use
reliable, volatile QoS with depth 10.

| Direction | Name | Type |
|---|---|---|
| Subscribe | `control/joint_states` | `sensor_msgs/JointState` |
| Publish | `feedback/joint_states` | `sensor_msgs/JointState` |
| Publish | `feedback/motor_status` | `diagnostic_msgs/DiagnosticArray` |
| Service | `enable` | `std_srvs/SetBool` |
| Service | `control_enable` | `std_srvs/SetBool` |

Command rules:

- `name` and `position` must be nonempty, equal length, with no duplicate names.
  Subsets are allowed; unknown joints are skipped.
- Only `position` is used; velocity/effort are ignored.
- Used values must be finite; an invalid packet is rejected before sending.
  Writes are per joint; a failed write is logged and other joints continue.
- Command headers are ignored; there is no age check or acknowledgment.

Joint feedback is published from cached SDK snapshots at `feedback_rate`.
Missing joints are omitted.

## Lift Behavior

**Position control only; MIT is not supported.** There is no `control_mode`
parameter. The first target per joint selects position mode, later targets keep
the mode unchanged, and disabling resets this tracking.

- Column (`torso_joint1`): position/velocity in m and m/s (`0.1 m` is `100 mm`);
  profile speed/acceleration in mm/s and mm/s^2. `effort` is scaled PWM, not
  measured force; do not use it for force control.
- Waist pitch (`torso_joint2`): rad, rad/s and N*m.
- YAML `torque_limit` is not applied by the node.

## Configuration

- [lift.yaml](config/lift.yaml): module `torso`, joints, IDs, protocols,
  polarity, limits and profile settings. Default column range: 0.0 to 0.4 m.
- [lift_ros.yaml](config/lift_ros.yaml): startup parameters.

To change the CAN interface, update any explicit per-joint `can_channel` fields too.

### Hardware YAML

Relative `yaml_path` values resolve under the installed `share/lift_ros/config`;
use absolute paths for external files (`package://` is not supported). An empty
`yaml_path` checks `LIFT_ROS_CONFIG`, then `lift.yaml`. For `lift.yaml` the module key defaults to `torso`. See the
[SDK YAML reference](https://github.com/kehuanjack/agx_motor_sdk/blob/main/YAML_CONFIG.md).

### ROS parameters

| Parameter | Node default | Meaning |
|---|---|---|
| `yaml_path` | empty | Hardware YAML; `lift_ros.yaml` sets `lift.yaml` |
| `module_key` | empty | Top-level YAML module; inferred from the file stem when empty |
| `can_channel` | empty | Override the YAML CAN interface |
| `auto_configure` | `true` | Configure the joint group at startup |
| `auto_enable` | `true` | Enable motors at startup |
| `control_enabled` | `true` | Initial software command gate |
| `feedback_rate` | `100.0` | Joint feedback rate, Hz |
| `status_rate` | `2.0` | Diagnostics rate, Hz |
| `status_timeout` | `2.0` | Low-speed feedback freshness bound, s |

Rates and timeout must be finite and positive. All parameters are read-only after startup.
Enable/disable frames are always sent 0.1 s apart per joint.
The gate parameter keeps its startup value; `control_enable` changes the live gate.
Launch accepts these overrides plus `namespace` and `params_file`; empty values
keep the parameter file. List them with
`ros2 launch lift_ros lift.launch.py --show-args`.

### Diagnostics

`/lift/feedback/motor_status` is one `DiagnosticArray` per publish with one
`DiagnosticStatus` per joint: `name` is the joint name and `hardware_id` is
`<can_channel>:<node_id>`. Values are strings.

Arm-protocol joints publish:

| Fields | Meaning |
|---|---|
| `enabled` | Hardware enable bit: `true`, `false`, `unknown` |
| `undervoltage`, `motor_overtemp`, `driver_overcurrent`, `driver_overtemp` | Fault bits |
| `collision_tripped`, `driver_error`, `stall_tripped` | Protection/error bits |
| `bus_voltage_v`, `bus_current` | Bus voltage (V), bus current |
| `driver_temp_deg`, `motor_temp_deg` | Temperatures (degrees C) |
| `status_raw` | Raw firmware status byte, decimal |
| `control_mode` | Software control mode |

Any fault bit gives `ERROR`.

RB200 joints publish the CiA 402 status word decoded by bit and by drive state:

| Fields | Meaning |
|---|---|
| `enabled` | Operation-enabled bit (bit 2) |
| `cia402_state` | `not_ready_to_switch_on`, `switch_on_disabled`, `ready_to_switch_on`, `switched_on`, `operation_enabled`, `quick_stop_active`, `fault_reaction_active` or `fault` |
| `ready_to_switch_on`, `switched_on`, `fault`, `voltage_enabled`, `switch_on_disabled`, `warning`, `remote`, `target_reached`, `internal_limit_active`, `homing_complete` | Status word bits 0, 1, 3, 4, 6, 7, 9, 10, 11, 15 |
| `quick_stop_active` | `true` in the quick-stop-active state |
| `error_code` | Raw RB200 error code, hex (`0x8130`) |
| `status_word` | Raw status word, hex (`0x1637`) |
| `control_mode` | `pos` |

The fault bit gives `ERROR` with the error code in the message; the warning
bit gives `WARN`; otherwise the message is the drive state.

Fresh, fault-free status is `OK`, even when disabled. Missing, nonpositive,
future or expired timestamps give `STALE` with values `unknown`. Freshness is
`0 <= age <= status_timeout` on host wall-clock time.

The column entry uses the arm fields and the waist entry uses the RB200 fields,
in the same array.

### Operating boundaries

- Closing the command gate does not disable motors or cancel sent targets.
- Stale diagnostics do not stop commands or expire cached joint feedback.
- Node exit closes the SDK connection without explicitly disabling motors.
- The enable service reports the SDK result; check diagnostics for hardware state.
- Provide watchdogs, trajectory execution and recovery upstream.

## License

Apache-2.0; see `LICENSE`.
