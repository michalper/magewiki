from pathlib import Path

from app.scanner.dto import QueueBindingEntry
from app.scanner.xml_parse_utils import parse_xml_root


def parse_queue_config(
    communication_path: Path, topology_path: Path, consumer_path: Path
) -> list[QueueBindingEntry]:
    """Parse a module's etc/communication.xml + etc/queue_topology.xml +
    etc/queue_consumer.xml into one structured fact per topic/queue — the same
    message-queue topology described from three different angles in real
    Magento modules (topic -> handler, exchange binding -> destination queue,
    consumer -> queue). Each file is optional and parsed independently
    (fail-open per file, same as every other parser here); merged by topic name
    (falling back to queue/destination name when a topic has no communication.xml
    entry of its own).
    """
    handlers: dict[str, tuple[str, str]] = {}
    if (comm_root := parse_xml_root(communication_path)) is not None:
        for topic_el in comm_root.findall("topic"):
            topic = topic_el.get("name")
            handler_el = topic_el.find("handler")
            if not topic or handler_el is None:
                continue
            handler_type = handler_el.get("type")
            handler_method = handler_el.get("method")
            if handler_type and handler_method:
                handlers[topic] = (handler_type, handler_method)

    destinations: dict[str, str] = {}
    if (topology_root := parse_xml_root(topology_path)) is not None:
        for binding_el in topology_root.findall(".//binding"):
            topic = binding_el.get("topic")
            destination = binding_el.get("destination")
            if topic and destination:
                destinations[topic] = destination

    consumers: dict[str, tuple[str, str | None, str | None]] = {}
    if (consumer_root := parse_xml_root(consumer_path)) is not None:
        for consumer_el in consumer_root.findall("consumer"):
            consumer_name = consumer_el.get("name")
            queue = consumer_el.get("queue")
            if not consumer_name or not queue:
                continue
            handler_class, handler_method = None, None
            if handler_attr := consumer_el.get("handler"):
                handler_class, _, handler_method = handler_attr.partition("::")
            consumers[queue] = (consumer_name, handler_class or None, handler_method or None)

    topics = set(handlers) | set(destinations)
    bindings: list[QueueBindingEntry] = []
    matched_queues: set[str] = set()
    for topic in topics:
        destination = destinations.get(topic)
        consumer = consumers.get(destination) if destination else consumers.get(topic)
        if consumer is not None:
            matched_queues.add(destination or topic)
        handler_class, handler_method = handlers.get(topic, (None, None))
        if handler_class is None and consumer is not None:
            handler_class, handler_method = consumer[1], consumer[2]
        bindings.append(
            QueueBindingEntry(
                topic=topic,
                destination=destination,
                consumer_name=consumer[0] if consumer else None,
                handler_class=handler_class,
                handler_method=handler_method,
            )
        )

    # Consumers whose queue never matched a topic/binding above (e.g. a
    # standalone consumer.xml entry with no corresponding topology binding in
    # this module) still represent a real queue a module consumes from.
    for queue, (consumer_name, handler_class, handler_method) in consumers.items():
        if queue in matched_queues:
            continue
        bindings.append(
            QueueBindingEntry(
                topic=queue,
                destination=queue,
                consumer_name=consumer_name,
                handler_class=handler_class,
                handler_method=handler_method,
            )
        )

    return bindings
