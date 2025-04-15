def get_server_properties(server_type):
    """Retrieve default server properties based on the server type."""
    server_properties = {
        'vanilla': {
            'max-players': 20,
            'level-type': 'DEFAULT',
            'difficulty': 'easy',
            'gamemode': 'survival',
            'pvp': 'true',
            'spawn-monsters': 'true',
            'spawn-animals': 'true',
            'enable-command-block': 'false',
            'view-distance': 10,
        },
        'paper': {
            'max-players': 20,
            'level-type': 'DEFAULT',
            'difficulty': 'easy',
            'gamemode': 'survival',
            'pvp': 'true',
            'spawn-monsters': 'true',
            'spawn-animals': 'true',
            'enable-command-block': 'false',
            'view-distance': 10,
            'use-async-chunks': 'true',
        },
        'forge': {
            'max-players': 20,
            'level-type': 'DEFAULT',
            'difficulty': 'easy',
            'gamemode': 'survival',
            'pvp': 'true',
            'spawn-monsters': 'true',
            'spawn-animals': 'true',
            'enable-command-block': 'false',
            'view-distance': 10,
        },
        'fabric': {
            'max-players': 20,
            'level-type': 'DEFAULT',
            'difficulty': 'easy',
            'gamemode': 'survival',
            'pvp': 'true',
            'spawn-monsters': 'true',
            'spawn-animals': 'true',
            'enable-command-block': 'false',
            'view-distance': 10,
        },
        'bedrock': {
            'max-players': 20,
            'difficulty': 'easy',
            'gamemode': 'survival',
            'pvp': 'true',
            'spawn-animals': 'true',
            'spawn-monsters': 'true',
        }
    }
    return server_properties.get(server_type, {})