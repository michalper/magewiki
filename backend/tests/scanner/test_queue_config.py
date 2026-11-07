from pathlib import Path

from app.scanner.queue_config import parse_queue_config

_COMMUNICATION_XML = """<?xml version="1.0"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:noNamespaceSchemaLocation="urn:magento:framework:Communication/etc/communication.xsd">
    <topic name="vendor.module.sample.dispatch" is_synchronous="false" request="string">
        <handler name="vendorModuleSampleDispatch"
                 type="Vendor\\Module\\Model\\Queue\\SampleConsumer" method="execute"/>
    </topic>
</config>
"""

_QUEUE_TOPOLOGY_XML = """<?xml version="1.0"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:noNamespaceSchemaLocation="urn:magento:framework-message-queue:etc/topology.xsd">
    <exchange name="magento">
        <binding id="VendorModuleSampleDispatch" topic="vendor.module.sample.dispatch"
                 destination="vendor.module.sample.dispatch"/>
    </exchange>
</config>
"""

_QUEUE_CONSUMER_XML = """<?xml version="1.0"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:noNamespaceSchemaLocation="urn:magento:framework-message-queue:etc/consumer.xsd">
    <consumer name="vendor.module.sample.dispatch" queue="vendor.module.sample.dispatch"
              handler="Vendor\\Module\\Model\\Queue\\SampleConsumer::execute"/>
</config>
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_queue_config_merges_all_three_files(tmp_path: Path):
    communication = _write(tmp_path, "communication.xml", _COMMUNICATION_XML)
    topology = _write(tmp_path, "queue_topology.xml", _QUEUE_TOPOLOGY_XML)
    consumer = _write(tmp_path, "queue_consumer.xml", _QUEUE_CONSUMER_XML)

    bindings = parse_queue_config(communication, topology, consumer)

    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.topic == "vendor.module.sample.dispatch"
    assert binding.destination == "vendor.module.sample.dispatch"
    assert binding.consumer_name == "vendor.module.sample.dispatch"
    assert binding.handler_class == "Vendor\\Module\\Model\\Queue\\SampleConsumer"
    assert binding.handler_method == "execute"


def test_parse_queue_config_missing_files(tmp_path: Path):
    bindings = parse_queue_config(
        tmp_path / "communication.xml", tmp_path / "queue_topology.xml", tmp_path / "queue_consumer.xml"
    )
    assert bindings == []


def test_parse_queue_config_standalone_consumer_with_no_topology(tmp_path: Path):
    # A consumer.xml entry with no corresponding topology binding in this module
    # still represents a real queue the module consumes from.
    consumer = _write(tmp_path, "queue_consumer.xml", _QUEUE_CONSUMER_XML)

    bindings = parse_queue_config(
        tmp_path / "communication.xml", tmp_path / "queue_topology.xml", consumer
    )

    assert len(bindings) == 1
    assert bindings[0].topic == "vendor.module.sample.dispatch"
    assert bindings[0].consumer_name == "vendor.module.sample.dispatch"
    assert bindings[0].handler_class == "Vendor\\Module\\Model\\Queue\\SampleConsumer"
