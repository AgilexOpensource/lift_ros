import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


class DiagnosticArray:
    def __init__(self):
        self.header = SimpleNamespace(stamp=None)
        self.status = []


class DiagnosticStatus:
    OK = 0
    WARN = 1
    ERROR = 2
    STALE = 3


@pytest.fixture
def lift_node(monkeypatch):
    class StubNode:
        parameter_overrides = {}

        def __init__(self, name):
            self.parameters = {}
            self.descriptors = {}
            self.timers = []

        def declare_parameter(self, name, default, descriptor=None):
            self.parameters[name] = self.parameter_overrides.get(name, default)
            self.descriptors[name] = descriptor

        def get_parameter(self, name):
            return SimpleNamespace(value=self.parameters[name])

        def create_publisher(self, *args):
            return SimpleNamespace(publish=lambda message: None)

        def create_subscription(self, *args):
            return SimpleNamespace()

        def create_service(self, *args):
            return SimpleNamespace()

        def create_timer(self, period, callback):
            self.timers.append((period, callback))
            return SimpleNamespace()

        def get_logger(self):
            return SimpleNamespace(info=lambda message: None, warn=lambda message: None)

    module_attributes = {
        "rclpy": {},
        "rclpy.node": {"Node": StubNode},
        "rclpy.executors": {"ExternalShutdownException": type("ExternalShutdownException", (Exception,), {})},
        "diagnostic_msgs": {},
        "diagnostic_msgs.msg": {
            "DiagnosticArray": DiagnosticArray,
            "DiagnosticStatus": DiagnosticStatus,
            "KeyValue": SimpleNamespace,
        },
        "rcl_interfaces": {},
        "rcl_interfaces.msg": {"ParameterDescriptor": SimpleNamespace},
        "ament_index_python": {},
        "ament_index_python.packages": {
            "get_package_share_directory": lambda name: "unused"
        },
        "sensor_msgs": {},
        "sensor_msgs.msg": {"JointState": SimpleNamespace},
        "std_srvs": {},
        "std_srvs.srv": {
            "SetBool": SimpleNamespace(Request=object, Response=object)
        },
        "agx_motor_sdk": {},
        "agx_motor_sdk.mechanism": {
            "JointGroup": SimpleNamespace(INVALID_JOINT_INDEX=-1)
        },
    }
    for name, attributes in module_attributes.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).parents[1] / "lift_ros" / "lift_node.py"
    spec = importlib.util.spec_from_file_location("lift_test_node", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "time_ns", lambda: 10_000_000_000)
    return module


def make_control_node(module, enabled=None):
    """``enabled``: joint index -> RB200 operation_enabled (default all enabled)."""
    calls = []
    enabled = {0: True, 1: True} if enabled is None else enabled
    node = module.LiftRosNode.__new__(module.LiftRosNode)
    node._recovered, node._recover_after, node._enable_wanted = {}, 0.0, True
    node._restoring, node._stale_joints, node._withheld = set(), set(), {}
    node._control_enabled = True
    node._control_gate_block_logged = False
    node._joint_names = ["joint1", "joint2"]
    node._joint_by_name = {"joint1": 0, "joint2": 1}
    node._position_mode_sent = {name: False for name in node._joint_names}
    node._disabled_logged = set()
    node._status_timeout = 2.0
    warnings = []

    def motor(index):
        def set_target(position, mode):
            calls.append((index, position, mode))
            return True
        feedback = SimpleNamespace(status=SimpleNamespace(operation_enabled=enabled[index]),
                                   timestamp_ns=9_000_000_000)
        return SimpleNamespace(set_target=set_target, protocol="rb200",
                               get_low_speed_feedback=lambda: feedback)

    node._group = SimpleNamespace(motor=motor)
    node.get_logger = lambda: SimpleNamespace(
        info=lambda message: None, warn=warnings.append,
        debug=lambda message: None,
    )
    node.warnings = warnings
    return node, calls


@pytest.mark.parametrize("position", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_command_rejected_atomically(lift_node, position):
    node, calls = make_control_node(lift_node)
    node._on_control(SimpleNamespace(name=["joint1", "joint2"], position=[0.2, position]))
    assert calls == []
    assert not any(node._position_mode_sent.values())


def test_duplicate_command_rejected(lift_node):
    node, calls = make_control_node(lift_node)
    node._on_control(SimpleNamespace(name=["joint1", "joint1"], position=[0.2, 0.3]))
    assert calls == []


def test_position_mode_sent_once(lift_node):
    node, calls = make_control_node(lift_node)
    for position in (0.2, 0.3):
        node._on_control(SimpleNamespace(name=["joint1"], position=[position]))
    assert calls == [(0, 0.2, 1), (0, 0.3, 0xFF)]


def test_re_enabled_rb200_resends_position_mode_before_ff(lift_node):
    node, calls = make_control_node(lift_node)
    node._position_mode_sent["joint1"] = True
    node._restoring = {0}
    for position in (0.2, 0.3):
        node._on_control(SimpleNamespace(name=["joint1"], position=[position]))
    assert calls == [(0, 0.2, 1), (0, 0.3, 0xFF)]
    assert node._restoring == set()


def test_enable_service_resends_position_mode(lift_node):
    node, calls = make_control_node(lift_node)
    node._position_mode_sent["joint1"] = True
    node._group.enable = lambda interval=0.0: True
    node._on_enable(SimpleNamespace(data=True), SimpleNamespace())
    node._on_control(SimpleNamespace(name=["joint1"], position=[0.2]))
    assert calls == [(0, 0.2, 1)]


def test_arm_protocol_sends_position_mode_every_frame(lift_node):
    node, calls = make_control_node(lift_node)
    feedback = SimpleNamespace(status=SimpleNamespace(enabled=True), timestamp_ns=9_000_000_000)

    def motor(index):
        return SimpleNamespace(
            set_target=lambda position, mode: calls.append((index, position, mode)) or True,
            protocol="arm", get_low_speed_feedback=lambda: feedback)

    node._group = SimpleNamespace(motor=motor)
    for position in (0.2, 0.3):
        node._on_control(SimpleNamespace(name=["joint1"], position=[position]))
    assert calls == [(0, 0.2, 1), (0, 0.3, 1)]


def test_disabled_motor_command_dropped_until_enabled(lift_node):
    enabled = {0: False, 1: True}
    node, calls = make_control_node(lift_node, enabled)
    for position in (0.2, 0.3):
        node._on_control(SimpleNamespace(name=["joint1", "joint2"], position=[position, position]))
    assert calls == [(1, 0.2, 1), (1, 0.3, 0xFF)]
    assert len(node.warnings) == 1 and "joint1" in node.warnings[0]   # warned once
    enabled[0] = True
    node._on_control(SimpleNamespace(name=["joint1"], position=[0.4]))
    assert calls[-1] == (0, 0.4, 1)                                    # position mode sent on enable


def test_stale_feedback_counts_as_disabled(lift_node, monkeypatch):
    node, calls = make_control_node(lift_node)
    monkeypatch.setattr(lift_node.time, "time_ns", lambda: 11_500_000_000)   # feedback 2.5 s old
    node._on_control(SimpleNamespace(name=["joint1"], position=[0.2]))
    assert calls == []


def test_closed_gate_blocks_command(lift_node):
    node, calls = make_control_node(lift_node)
    node._control_enabled = False
    node._on_control(SimpleNamespace(name=["joint1"], position=[0.2]))
    assert calls == []


def make_feedback(enabled=True, timestamp_ns=9_000_000_000):
    return SimpleNamespace(
        status=SimpleNamespace(
            enabled=enabled, undervoltage=False, motor_overtemp=False,
            driver_overcurrent=False, driver_overtemp=False, collision_tripped=False,
            driver_error=False, stall_tripped=False,
        ),
        timestamp_ns=timestamp_ns, bus_voltage_v=48.0, driver_temp_deg=35,
        motor_temp_deg=40, bus_current=1.2, status_raw=64 if enabled else 0,
    )


def publish_status(module, feedbacks):
    node = module.LiftRosNode.__new__(module.LiftRosNode)
    node._recovered, node._recover_after, node._enable_wanted = {}, 0.0, True
    node._restoring, node._stale_joints, node._withheld = set(), set(), {}
    motors = [
        SimpleNamespace(
            can_channel="can%d" % index, node_id=index + 1,
            get_low_speed_feedback=(
                feedback if callable(feedback) else (lambda feedback=feedback: feedback)
            ),
        )
        for index, feedback in enumerate(feedbacks)
    ]
    node._group = SimpleNamespace(joint_count=len(motors), motor=motors.__getitem__)
    node._joint_names = ["joint%d" % (index + 1) for index in range(len(motors))]
    node._status_timeout = 2.0
    published = []
    node._status_pub = SimpleNamespace(publish=published.append)
    node.get_clock = lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(to_msg=lambda: "ros_stamp")
    )
    node._publish_status()
    assert len(published) == 1
    assert published[0].header.stamp == "ros_stamp"
    for status in published[0].status:
        assert {entry.key for entry in status.values} == {
            "enabled", "undervoltage", "motor_overtemp", "driver_overcurrent",
            "driver_overtemp", "collision_tripped", "driver_error", "stall_tripped",
            "bus_voltage_v", "driver_temp_deg", "motor_temp_deg", "bus_current",
            "status_raw", "control_mode",
        }
    return published[0].status


def test_enabled_disabled_and_unavailable_status(lift_node):
    statuses = publish_status(lift_node, [make_feedback(), make_feedback(False), None])
    assert [status.name for status in statuses] == ["joint1", "joint2", "joint3"]
    assert [status.hardware_id for status in statuses] == ["can0:1", "can1:2", "can2:3"]
    assert [status.level for status in statuses] == [0, 0, 3]
    assert [status.values[0].value for status in statuses] == ["true", "false", "unknown"]


@pytest.mark.parametrize("timestamp_ns", [0, -1, 7_999_999_999, 10_000_000_001])
def test_expired_or_invalid_feedback_is_unknown(lift_node, timestamp_ns):
    status = publish_status(lift_node, [make_feedback(timestamp_ns=timestamp_ns)])[0]
    assert status.level == DiagnosticStatus.STALE
    assert status.values[0].value == "unknown"
    assert all(
        entry.value == "unknown" for entry in status.values if entry.key != "control_mode"
    )


def test_timeout_boundary_and_status_fields(lift_node):
    status = publish_status(lift_node, [make_feedback(timestamp_ns=8_000_000_000)])[0]
    values = {value.key: value.value for value in status.values}
    assert status.level == DiagnosticStatus.OK
    assert values["bus_voltage_v"] == "48.0"
    assert values["driver_temp_deg"] == "35"
    assert values["motor_temp_deg"] == "40"
    assert values["bus_current"] == "1.2"
    assert values["status_raw"] == "64"
    assert values["control_mode"] == "pos"


@pytest.mark.parametrize("fault", [
    "undervoltage", "motor_overtemp", "driver_overcurrent", "driver_overtemp",
    "collision_tripped", "driver_error", "stall_tripped",
])
def test_fault_feedback_reports_error(lift_node, fault):
    feedback = make_feedback()
    setattr(feedback.status, fault, True)
    status = publish_status(lift_node, [feedback])[0]
    assert status.level == DiagnosticStatus.ERROR
    assert status.message == fault


def configure_startup(module, monkeypatch):
    closed = []
    group = SimpleNamespace(
        joint_names=["joint1"], joint_count=1, index_of=lambda name: 0,
        can_channel="can0", connect=lambda: True, configure=lambda: True,
        enable_intervals=[], close=lambda: closed.append(True),
    )
    group.enable = lambda interval=0.0: group.enable_intervals.append(interval) or True
    monkeypatch.setattr(module, "resolve_yaml_path", lambda value: Path("lift.yaml"))
    monkeypatch.setattr(module.JointGroup, "from_yaml", lambda *args: group, raising=False)
    return group, closed


@pytest.mark.parametrize("method", ["connect", "configure", "enable"])
def test_startup_failure_closes_group(lift_node, monkeypatch, method):
    group, closed = configure_startup(lift_node, monkeypatch)
    setattr(group, method, lambda *args: False)
    with pytest.raises(RuntimeError):
        lift_node.LiftRosNode()
    assert closed == [True]


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf")])
def test_invalid_feedback_timeout_rejected_before_connect(lift_node, value):
    lift_node.LiftRosNode.__bases__[0].parameter_overrides = {"feedback_timeout": value}
    with pytest.raises(ValueError, match="feedback_timeout must be finite and >= 0"):
        lift_node.LiftRosNode()


@pytest.mark.parametrize("parameter", ["feedback_rate", "status_rate", "status_timeout"])
@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_rates_rejected_before_connect(lift_node, parameter, value):
    lift_node.LiftRosNode.__bases__[0].parameter_overrides = {parameter: value}
    with pytest.raises(ValueError, match="finite and > 0"):
        lift_node.LiftRosNode()


def test_startup_parameters_readonly_and_default_rates(lift_node, monkeypatch):
    configure_startup(lift_node, monkeypatch)
    node = lift_node.LiftRosNode()
    assert len(node.descriptors) == 10
    assert all(descriptor.read_only for descriptor in node.descriptors.values())
    assert [period for period, _ in node.timers] == pytest.approx([0.01, 1.0 / 30.0])


def test_enable_uses_frame_interval(lift_node, monkeypatch):
    group, _ = configure_startup(lift_node, monkeypatch)
    node = lift_node.LiftRosNode()
    assert group.enable_intervals == [0.1]
    disable_intervals = []
    group.disable = lambda interval=0.0: disable_intervals.append(interval) or True
    for data in (True, False):
        node._on_enable(SimpleNamespace(data=data), SimpleNamespace())
    assert group.enable_intervals == [0.1, 0.1]
    assert disable_intervals == [0.1]


def test_main_shuts_down_after_construction_failure(lift_node, monkeypatch):
    closed = []
    monkeypatch.setattr(lift_node.rclpy, "init", lambda **kwargs: None, raising=False)
    monkeypatch.setattr(lift_node.rclpy, "try_shutdown", lambda: closed.append(True), raising=False)
    monkeypatch.setattr(lift_node, "LiftRosNode", lambda: (_ for _ in ()).throw(RuntimeError("startup")))
    with pytest.raises(RuntimeError, match="startup"):
        lift_node.main()
    assert closed == [True]


RB200_BIT_POSITIONS = {
    "ready_to_switch_on": 0, "switched_on": 1, "operation_enabled": 2, "fault": 3,
    "voltage_enabled": 4, "quick_stop": 5, "switch_on_disabled": 6, "warning": 7,
    "remote": 9, "target_reached": 10, "internal_limit_active": 11, "homing_complete": 15,
}
RB200_KEYS = {
    "enabled", "cia402_state", "ready_to_switch_on", "switched_on", "fault", "voltage_enabled",
    "switch_on_disabled", "warning", "remote", "target_reached", "internal_limit_active",
    "homing_complete", "quick_stop_active", "error_code", "status_word", "control_mode",
}


def make_rb200_feedback(status_word, timestamp_ns=9_000_000_000, error_code=0):
    return SimpleNamespace(
        status_word=status_word, error_code=error_code, tpdo2_count=1,
        status=SimpleNamespace(**{
            name: bool(status_word >> bit & 1) for name, bit in RB200_BIT_POSITIONS.items()
        }),
        timestamp_ns=timestamp_ns,
    )


def publish_rb200_status(module, feedbacks):
    node = module.LiftRosNode.__new__(module.LiftRosNode)
    node._recovered, node._recover_after, node._enable_wanted = {}, 0.0, True
    node._restoring, node._stale_joints, node._withheld = set(), set(), {}
    motors = [
        SimpleNamespace(
            can_channel="can0", node_id=index + 1, protocol="rb200",
            get_low_speed_feedback=(
                feedback if callable(feedback) else (lambda feedback=feedback: feedback)
            ),
        )
        for index, feedback in enumerate(feedbacks)
    ]
    node._group = SimpleNamespace(joint_count=len(motors), motor=motors.__getitem__)
    node._joint_names = ["joint%d" % (index + 1) for index in range(len(motors))]
    node._status_timeout = 2.0
    node._control_mode = "pos"
    published = []
    node._status_pub = SimpleNamespace(publish=published.append)
    node.get_clock = lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(to_msg=lambda: "ros_stamp")
    )
    node._publish_status()
    return published[0].status


def test_rb200_status_word_published(lift_node):
    statuses = publish_rb200_status(lift_node, [
        make_rb200_feedback(0x0637), make_rb200_feedback(0x0631),
        make_rb200_feedback(0x0638), make_rb200_feedback(0x0637, 7_000_000_000), None,
    ])
    values = [{entry.key: entry.value for entry in status.values} for status in statuses]
    assert set(values[0]) == RB200_KEYS
    assert [v["status_word"] for v in values] == [
        "0x0637", "0x0631", "0x0638", "unknown", "unknown",
    ]
    assert [v["enabled"] for v in values] == ["true", "false", "false", "unknown", "unknown"]
    assert [status.level for status in statuses] == [
        DiagnosticStatus.OK, DiagnosticStatus.OK, DiagnosticStatus.ERROR,
        DiagnosticStatus.STALE, DiagnosticStatus.STALE,
    ]
    assert [status.message for status in statuses[:3]] == ["operation_enabled", "ready_to_switch_on", "fault, error_code 0x0000"]


def test_mixed_arm_and_rb200_status(lift_node):
    node = lift_node.LiftRosNode.__new__(lift_node.LiftRosNode)
    node._recovered, node._recover_after, node._enable_wanted = {}, 0.0, True
    node._restoring, node._stale_joints, node._withheld = set(), set(), {}
    motors = [
        SimpleNamespace(can_channel="can0", node_id=1, protocol="arm",
                        get_low_speed_feedback=lambda: make_feedback()),
        SimpleNamespace(can_channel="can0", node_id=2, protocol="rb200",
                        get_low_speed_feedback=lambda: make_rb200_feedback(0x0637)),
    ]
    node._group = SimpleNamespace(joint_count=2, motor=motors.__getitem__)
    node._joint_names = ["torso_joint1", "torso_joint2"]
    node._status_timeout = 2.0
    published = []
    node._status_pub = SimpleNamespace(publish=published.append)
    node.get_clock = lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(to_msg=lambda: "ros_stamp")
    )
    node._publish_status()
    assert len(published) == 1
    column, waist = published[0].status
    column_values = {entry.key: entry.value for entry in column.values}
    waist_values = {entry.key: entry.value for entry in waist.values}
    assert column_values["status_raw"] == "64"
    assert "bus_voltage_v" in column_values and "status_word" not in column_values
    assert waist_values["status_word"] == "0x0637"
    assert set(waist_values) == RB200_KEYS
    assert [column.level, waist.level] == [DiagnosticStatus.OK, DiagnosticStatus.OK]


def test_rb200_cia402_state_decoding(lift_node):
    cia402_state = lift_node.cia402_state

    assert cia402_state(0x0000) == "not_ready_to_switch_on"
    assert cia402_state(0x0040) == "switch_on_disabled"
    assert cia402_state(0x0021) == "ready_to_switch_on"
    assert cia402_state(0x0023) == "switched_on"
    assert cia402_state(0x1637) == "operation_enabled"
    assert cia402_state(0x0007) == "quick_stop_active"
    assert cia402_state(0x000F) == "fault_reaction_active"
    assert cia402_state(0x0008) == "fault"


def test_rb200_status_bits_and_error_code(lift_node):
    statuses = publish_rb200_status(lift_node, [
        make_rb200_feedback(0x1637), make_rb200_feedback(0x0638, error_code=0x8130),
        make_rb200_feedback(0x00B7), make_rb200_feedback(0x0017),
    ])
    values = [{item.key: item.value for item in status.values} for status in statuses]

    assert values[0]["cia402_state"] == "operation_enabled"
    assert values[0]["target_reached"] == "true"
    assert values[0]["remote"] == "true"
    assert values[0]["quick_stop_active"] == "false"
    assert values[1]["error_code"] == "0x8130"
    assert statuses[1].message == "fault, error_code 0x8130"
    assert statuses[2].level == DiagnosticStatus.WARN
    assert values[2]["warning"] == "true"
    assert values[3]["cia402_state"] == "quick_stop_active"
    assert values[3]["quick_stop_active"] == "true"


def make_receive_then_read(module, monkeypatch, make):
    clock = [10_000_000_000]
    monkeypatch.setattr(module.time, "time_ns", lambda: clock[0])

    def receive_then_read():
        clock[0] += 1_000
        return make(clock[0])

    return receive_then_read


def test_frame_cached_during_publish_is_fresh(lift_node, monkeypatch):
    read = make_receive_then_read(
        lift_node, monkeypatch, lambda stamp: make_feedback(timestamp_ns=stamp)
    )
    statuses = publish_status(lift_node, [read, read])
    assert [status.level for status in statuses] == [DiagnosticStatus.OK] * 2


def test_rb200_frame_cached_during_publish_is_fresh(lift_node, monkeypatch):
    read = make_receive_then_read(
        lift_node, monkeypatch, lambda stamp: make_rb200_feedback(0x0637, stamp)
    )
    statuses = publish_rb200_status(lift_node, [read, read])
    assert [status.level for status in statuses] == [DiagnosticStatus.OK] * 2


def make_feedback_node(module, cls, stamps, timeout=0.5):
    """Node with one joint per entry in ``stamps`` (high-speed feedback timestamp, ns)."""
    module.JointState = lambda: SimpleNamespace(header=SimpleNamespace())
    node = cls.__new__(cls)
    node._recovered, node._recover_after, node._enable_wanted = {}, 0.0, True
    node._restoring, node._stale_joints, node._withheld = set(), set(), {}
    node._feedback_timeout = timeout
    node._stale_joints = set()
    node._joint_names = ["joint%d" % i for i in range(len(stamps))]
    published, logs = [], []
    node._feedback_pub = SimpleNamespace(publish=published.append)
    node.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: None))
    node.get_logger = lambda: SimpleNamespace(warn=logs.append, info=logs.append)

    def motor(index):
        stamp = stamps[index]
        feedback = None if stamp is None else SimpleNamespace(timestamp_ns=stamp)
        return SimpleNamespace(get_high_speed_feedback=lambda: feedback)

    def get_state(index):
        return SimpleNamespace(position_rad=0.1 * index, velocity_rad_s=0.0, torque_nm=0.0)

    node._group = SimpleNamespace(joint_count=len(stamps), motor=motor, get_state=get_state)
    return node, published, logs


def test_feedback_older_than_timeout_is_not_published(lift_node):
    # time_ns is 10 s; joint1 is 0.6 s old; joint2 and joint3 have no usable stamp, so cannot be judged
    stamps = [9_600_000_000, 9_400_000_000, 0, None]
    node, published, logs = make_feedback_node(lift_node, lift_node.LiftRosNode, stamps)
    node._publish_feedback()
    assert published[-1].name == ["joint0", "joint2", "joint3"]
    assert logs == ["joint1 feedback older than 0.50 s, not published"]
    node._publish_feedback()
    assert len(logs) == 1


def test_feedback_timeout_zero_publishes_cached_samples(lift_node):
    node, published, _ = make_feedback_node(lift_node, lift_node.LiftRosNode, [1, 1], timeout=0.0)
    node._publish_feedback()
    assert published[-1].name == ["joint0", "joint1"]


def test_stale_joint_is_published_again_once_released(lift_node):
    stamps = [9_000_000_000]
    node, published, logs = make_feedback_node(lift_node, lift_node.LiftRosNode, stamps)
    node._publish_feedback()
    assert published == []
    stamps[0] = 10_000_000_000
    node._publish_feedback()
    assert published == [] and 0 in node._withheld
    assert logs[-1] == "joint0 feedback recovered"
    node._withheld.clear()
    node._publish_feedback()
    assert published[-1].name == ["joint0"]


def make_restore_node(module, monkeypatch, enabled=False, status_ns=10_100_000_000, recovered=True):
    calls = []
    clock = [100.0]
    monkeypatch.setattr(module.time, "time_ns", lambda: 10_200_000_000)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    bits = dict.fromkeys(module.MOTOR_FAULT_FIELDS, False)
    status = SimpleNamespace(status=SimpleNamespace(enabled=enabled, **bits), timestamp_ns=status_ns)
    node = module.LiftRosNode.__new__(module.LiftRosNode)
    node._recovered = {0: 10_000_000_000} if recovered else {}
    node._recover_after, node._enable_wanted, node._restoring = 0.0, True, set()
    node._withheld, node._feedback_timeout = {}, 0.5
    node._joint_names = ["joint0"]
    node._stale_joints = set()
    node._auto_configure = True
    node._status_timeout = 2.0
    node._position_mode_sent = {"joint0": True}
    motor = SimpleNamespace(protocol="arm", get_low_speed_feedback=lambda: status,
                            configure=lambda: calls.append("configure") or True)
    node._group = SimpleNamespace(
        motor=lambda index: motor,
        enable=lambda interval=0.0: calls.append("enable") or node.enable_ok,
    )
    node.enable_ok = True
    node.logs = []
    node.get_logger = lambda: SimpleNamespace(info=node.logs.append, warn=node.logs.append)
    return node, status, calls, clock


def test_power_loss_reconfigures_and_restores_a_wanted_enable(lift_node, monkeypatch):
    node, status, calls, clock = make_restore_node(lift_node, monkeypatch)
    node._restore_enable()
    assert calls == ["configure", "enable"]
    assert node._position_mode_sent == {"joint0": False}
    node._restore_enable()
    assert calls == ["configure", "enable"]
    status.status.enabled = True
    clock[0] += 1.0
    node._restore_enable()
    assert node._recovered == {} and node._restoring == set()
    assert node.logs[-1] == "joint0 re-enabled"


def test_power_loss_keeps_a_disabled_module_disabled(lift_node, monkeypatch):
    node, _, calls, _ = make_restore_node(lift_node, monkeypatch)
    node._position_mode_sent = {"joint0": True}
    node._group.disable = lambda interval=0.0: False
    node._on_enable(SimpleNamespace(data=False), SimpleNamespace())
    calls.clear()
    node._restore_enable()
    assert calls == [] and node._recovered == {}


def test_restore_waits_for_reconnect_then_a_status_sent_after_it(lift_node, monkeypatch):
    node, status, calls, _ = make_restore_node(lift_node, monkeypatch, status_ns=9_500_000_000)
    node._stale_joints = {"joint0"}
    node._recovered = {}
    node._restore_enable()
    assert calls == []
    node._stale_joints = set()
    node._recovered = {0: 10_000_000_000}
    node._restore_enable()
    assert calls == []
    status.timestamp_ns = 10_100_000_000
    node._restore_enable()
    assert calls[-1] == "enable" and "configure" in calls


def test_estop_release_reconfigures_and_enables(lift_node, monkeypatch):
    node, status, calls, clock = make_restore_node(lift_node, monkeypatch, recovered=False)
    status.status.stall_tripped = True
    node._restore_enable()
    assert calls == []
    status.status.stall_tripped = False
    node._restore_enable()
    assert calls[0] == "configure" and calls[-1] == "enable"


def test_rb200_fault_is_not_re_enabled(lift_node, monkeypatch):
    node, status, calls, _ = make_restore_node(lift_node, monkeypatch, recovered=False)
    node._group.motor(0).protocol = "rb200"
    status.status = SimpleNamespace(operation_enabled=False, fault=True)
    node._restore_enable()
    assert calls == []
    status.status.fault = False
    node._restore_enable()
    assert calls[-1] == "enable"


def test_unconfirmed_restore_retries_after_a_second_and_warns_once(lift_node, monkeypatch):
    node, _, calls, clock = make_restore_node(lift_node, monkeypatch, recovered=False)
    node.enable_ok = False
    node._restore_enable()
    node._restore_enable()
    assert calls.count("enable") == 1
    clock[0] += 1.0
    node.enable_ok = True
    node._restore_enable()
    clock[0] += 1.0
    node._restore_enable()
    assert calls.count("enable") == 3
    assert sum("re-enabling" in log for log in node.logs) == 1


def test_restoring_joint_is_withheld_until_enabled_for_feedback_timeout(lift_node, monkeypatch):
    node, status, calls, clock = make_restore_node(lift_node, monkeypatch, recovered=False)
    node._restore_enable()
    assert node._withheld == {0: 100.0} and calls[-1] == "enable"
    status.status.enabled = True
    node._position_mode_sent = {"joint0": True}
    clock[0] += 0.3
    node._restore_enable()
    assert 0 in node._withheld
    clock[0] += 0.2
    node._restore_enable()
    assert node._withheld == {}
    assert node._position_mode_sent == {"joint0": False}


def test_faulted_joint_feedback_is_not_withheld(lift_node, monkeypatch):
    node, status, _, _ = make_restore_node(lift_node, monkeypatch, recovered=False)
    node._restore_enable()
    status.status.stall_tripped = True
    node._restore_enable()
    assert node._withheld == {}


def test_manual_disable_releases_withheld_feedback(lift_node, monkeypatch):
    node, _, _, _ = make_restore_node(lift_node, monkeypatch, recovered=False)
    node._restore_enable()
    node._enable_wanted = False
    node._restore_enable()
    assert node._withheld == {}


def test_withheld_joint_drops_targets(lift_node):
    node, calls = make_control_node(lift_node)
    node._position_mode_sent["joint1"] = True
    node._withheld = {0: 0.0}
    node._on_control(SimpleNamespace(name=["joint1", "joint2"], position=[0.2, 0.3]))
    assert calls == [(1, 0.3, 1)]
    assert node._position_mode_sent["joint1"] is False
