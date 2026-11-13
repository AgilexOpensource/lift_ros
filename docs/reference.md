# lift_ros reference

[中文](reference.zh-CN.md)

Parameters, hardware YAML, diagnostics and operating boundaries of `lift_node`. Start with the [README](../README.md).

## ROS parameters

| Parameter | Default | Description |
|---|---|---|
| `yaml_path` | empty | Hardware YAML; [lift_ros.yaml](../config/lift_ros.yaml) sets `lift.yaml` |
| `module_key` | empty | Top-level YAML module; [lift_ros.yaml](../config/lift_ros.yaml) sets `torso` |
| `can_channel` | empty | CAN interface override; [lift_ros.yaml](../config/lift_ros.yaml) sets `can0` |
| `auto_configure` | `true` | Configure the joint group at startup |
| `auto_enable` | `true` | Enable the motors at startup |
| `control_enabled` | `true` | Initial command gate |
| `feedback_rate` | `100.0` | Joint feedback rate, Hz |
| `status_rate` | `2.0` | Diagnostics rate, Hz |
| `status_timeout` | `2.0` | Diagnostics freshness bound, s |

- Rates and `status_timeout` must be finite and greater than 0.
- All parameters are read-only after startup.
- `control_enabled` keeps its startup value; the `control_enable` service changes the live gate.
- Per-joint enable and disable frames are sent 0.1 s apart.

## Hardware YAML

- A relative `yaml_path` is looked up under the installed `share/lift_ros/config`. Use an absolute path for other files; `package://` URLs are not supported.
- An empty `yaml_path` uses the `LIFT_ROS_CONFIG` environment variable, then `lift.yaml`.
- An empty `module_key` uses the file stem, except that `lift.yaml` maps to module `torso`.
- `can_channel` replaces the module default and every joint channel equal to it.

Field meanings are in the [SDK YAML reference](https://github.com/kehuanjack/agx_motor_sdk/blob/main/YAML_CONFIG.md). In [lift.yaml](../config/lift.yaml), the column uses `polarity: 0.001` to map joint m to motor mm, and its profile is in mm/s and mm/s². `torque_limit` is not applied by this driver.

## Diagnostics

`feedback/motor_status` publishes one `DiagnosticArray` with one `DiagnosticStatus` per joint. `name` is the joint name, `hardware_id` is `<can_channel>:<node_id>` and all values are strings. `control_mode` is always `pos`.

Column (`torso_joint1`, arm protocol):

| Key | Description |
|---|---|
| `enabled` | Hardware enable bit |
| `undervoltage`, `motor_overtemp`, `driver_overcurrent`, `driver_overtemp` | Fault bits |
| `collision_tripped`, `driver_error`, `stall_tripped` | Protection and error bits |
| `bus_voltage_v`, `bus_current` | Bus voltage (V) and bus current |
| `driver_temp_deg`, `motor_temp_deg` | Temperatures, °C |
| `status_raw` | Raw firmware status byte, decimal |

Any active fault or protection bit gives `ERROR` and lists the bits in the message. Otherwise the status is `OK` with message `enabled` or `disabled`.

Waist pitch (`torso_joint2`, RB200 protocol, CiA 402 status word):

| Key | Description |
|---|---|
| `enabled` | `operation_enabled` state |
| `cia402_state` | Drive state, such as `switch_on_disabled`, `operation_enabled` or `fault` |
| `ready_to_switch_on`, `switched_on`, `fault`, `voltage_enabled`, `switch_on_disabled` | Status word bits 0, 1, 3, 4, 6 |
| `warning`, `remote`, `target_reached`, `internal_limit_active`, `homing_complete` | Status word bits 7, 9, 10, 11, 15 |
| `quick_stop_active` | Drive is in the quick stop state |
| `error_code`, `status_word` | Hex, such as `0x0000` |

The `fault` bit gives `ERROR` with message `<state>, error_code 0x....`; the `warning` bit gives `WARN`. Otherwise the status is `OK` with the drive state as message.

For both protocols, missing, nonpositive, future or expired timestamps give `STALE` with values `unknown`. Fresh means `0 <= age <= status_timeout` on the host wall clock.

## Operating boundaries

- Closing the command gate does not disable the motors or cancel targets already sent.
- Stale diagnostics do not stop commands or clear cached joint feedback.
- Node exit closes the SDK connection without disabling the motors; the column then depends on its mechanical load support.
- The `enable` service reports the SDK result; read `motor_status` for the hardware state.
- Watchdogs, trajectory execution and fault recovery belong upstream of this driver.
