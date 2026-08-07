from src.market.message_dispatcher import MessageDispatcher


def test_register_handler() -> None:
    dispatcher = MessageDispatcher()

    def handler(message) -> None:
        pass

    dispatcher.register(handler)

    assert dispatcher.count() == 1


def test_duplicate_handler_is_not_registered_twice() -> None:
    dispatcher = MessageDispatcher()

    def handler(message) -> None:
        pass

    dispatcher.register(handler)
    dispatcher.register(handler)

    assert dispatcher.count() == 1


def test_dispatch_calls_registered_handler() -> None:
    dispatcher = MessageDispatcher()
    received = []

    def handler(message) -> None:
        received.append(message)

    dispatcher.register(handler)

    message = {"security_id": "13", "ltp": 25000.0}

    dispatcher.dispatch(message)

    assert received == [message]


def test_dispatch_calls_multiple_handlers() -> None:
    dispatcher = MessageDispatcher()

    first = []
    second = []

    dispatcher.register(first.append)
    dispatcher.register(second.append)

    dispatcher.dispatch("tick")

    assert first == ["tick"]
    assert second == ["tick"]


def test_unregister_handler() -> None:
    dispatcher = MessageDispatcher()
    received = []

    def handler(message) -> None:
        received.append(message)

    dispatcher.register(handler)

    assert dispatcher.unregister(handler) is True
    assert dispatcher.count() == 0

    dispatcher.dispatch("tick")

    assert received == []


def test_unregister_unknown_handler_returns_false() -> None:
    dispatcher = MessageDispatcher()

    def handler(message) -> None:
        pass

    assert dispatcher.unregister(handler) is False


def test_clear_handlers() -> None:
    dispatcher = MessageDispatcher()

    dispatcher.register(lambda message: None)
    dispatcher.register(lambda message: None)

    assert dispatcher.count() == 2

    dispatcher.clear()

    assert dispatcher.count() == 0


def test_handler_can_unregister_during_dispatch() -> None:
    dispatcher = MessageDispatcher()
    received = []

    def first_handler(message) -> None:
        received.append("first")
        dispatcher.unregister(first_handler)

    def second_handler(message) -> None:
        received.append("second")

    dispatcher.register(first_handler)
    dispatcher.register(second_handler)

    dispatcher.dispatch("tick")

    assert received == ["first", "second"]
    assert dispatcher.count() == 1