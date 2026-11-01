"""Same bounded cleanup, with a diagnostic-completion marker instead of idle pass."""
from supervise_idle import main

if __name__ == '__main__':
    main(diagnostic=True)
