import subprocess
import sys
import time

from driftwatch_llm.agent.lock import FileLock


def test_a_second_holder_is_refused_until_the_first_releases(tmp_path):
    path = tmp_path / "agent" / "agent.lock"
    first, second = FileLock(path), FileLock(path)
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_acquire_twice_on_the_same_object_is_fine(tmp_path):
    lock = FileLock(tmp_path / "x.lock")
    assert lock.acquire() and lock.acquire()
    lock.release()
    lock.release()  # releasing twice is harmless


def test_the_os_releases_the_lock_when_the_holder_is_killed_hard(tmp_path):
    path = tmp_path / "k.lock"
    code = (
        "import sys, time\n"
        "from driftwatch_llm.agent.lock import FileLock\n"
        f"lock = FileLock(r'{path}')\n"
        "assert lock.acquire()\n"
        "print('held', flush=True)\n"
        "time.sleep(60)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "held"
        mine = FileLock(path)
        assert mine.acquire() is False  # a live holder blocks us
        child.kill()  # SIGKILL / TerminateProcess: no cleanup code runs
        child.wait(timeout=10)
        deadline = time.time() + 5
        got = False
        while time.time() < deadline and not got:
            got = mine.acquire()
            time.sleep(0.05)
        assert got, "the lock stayed held after the holder died"
        mine.release()
    finally:
        if child.poll() is None:
            child.kill()
