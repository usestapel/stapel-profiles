# stapel-profiles

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

## Contributing

The source for this package lives inside the [client-project-backend](https://github.com/UCSoftworks) monorepo as a git submodule.

## License

MIT — see [LICENSE](LICENSE)
