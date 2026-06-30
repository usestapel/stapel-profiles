# stapel-profiles

[![CI](https://github.com/usestapel/stapel-profiles/actions/workflows/ci.yml/badge.svg)](https://github.com/usestapel/stapel-profiles/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/usestapel/stapel-profiles/graph/badge.svg)](https://codecov.io/gh/usestapel/stapel-profiles)

> User profiles — avatars, social graph (follow/block), privacy settings, language preferences

Part of the [Stapel framework](https://github.com/usestapel) — composable Django apps for building production-grade platforms.

## Installation

```bash
pip install stapel-profiles
```

## Quick start

```python
# settings.py
INSTALLED_APPS = [
    ...
    'stapel_profiles',
]
```

## Bus events

### Emits
| `profile.updated` | [schema](schemas/emits/profile.updated.json) | User profile fields were updated. |

### Consumes
| `user.deleted` | [schema](schemas/consumes/user.deleted.json) |
| `user.deletion_initiated` | [schema](schemas/consumes/user.deletion_initiated.json) |

## License

MIT — see [LICENSE](LICENSE)
