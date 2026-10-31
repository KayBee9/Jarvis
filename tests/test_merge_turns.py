import copy

from app.agent import merge_consecutive_user_turns


def user(text):
    return {"role": "user", "content": text}


def jarvis(text):
    return {"role": "assistant", "content": text}


def test_empty_history_stays_empty():
    assert merge_consecutive_user_turns([]) == []


def test_single_message_is_unchanged():
    assert merge_consecutive_user_turns([user("Hi")]) == [user("Hi")]


def test_two_user_turns_merge_in_order():
    assert merge_consecutive_user_turns([user("How are you?"), user("Get me chocolate")]) == [
        user("How are you?\n\nGet me chocolate")
    ]


def test_three_user_turns_merge_into_one():
    assert merge_consecutive_user_turns([user("a"), user("b"), user("c")]) == [user("a\n\nb\n\nc")]


def test_normal_back_and_forth_is_unchanged():
    history = [user("Hi"), jarvis("Hello"), user("Bye")]
    assert merge_consecutive_user_turns(history) == history


def test_only_the_unanswered_turns_merge():
    assert merge_consecutive_user_turns([user("Hi"), jarvis("Hello"), user("a"), user("b")]) == [
        user("Hi"),
        jarvis("Hello"),
        user("a\n\nb"),
    ]


def test_consecutive_assistant_turns_are_not_merged():
    history = [jarvis("a"), jarvis("b")]
    assert merge_consecutive_user_turns(history) == history


def test_input_list_is_not_modified():
    history = [user("a"), user("b")]
    original = copy.deepcopy(history)
    merge_consecutive_user_turns(history)
    assert history == original
