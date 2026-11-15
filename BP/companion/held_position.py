# -*- coding: utf-8 -*-
# Held transforms in Bedrock model units. User-edited third-person poses.
# Lower on the upright doll axis; the rotated item socket's Y points upward
# on screen when reduced. Keep this correction separate from the hand socket.
FIRST_PERSON = {'body_position': (0.0, -4.0, 0.0),
 'body_rotation': (-10.0, 230.0, 7.0),
 'position': (3.0, 19.0, 4.0),
 'rotation': (66.0, 60.0, -60.0),
 'scale': 0.64}

# One gentle cycle per 1.25 seconds; independent of the doll's walking stride.
FIRST_PERSON_BOUNCE = {'frequency': .8, 'height': .4, 'squash': .006, 'stretch': .01}

THIRD_PERSON = {'hold': {'body_position': (-0.0, 1.0, 8.0),
          'body_rotation': (92.5, -0.0, 0.0),
          'position': (-6.0, 10.5, -3.0),
          'rotation': (0.0, 0.0, 0.0),
          'scale': 0.6},
 'hug': {'body_position': (-0.0, 0.0, -1.0),
         'body_rotation': (-0.0, -0.0, 0.0),
         'position': (-0.0, 11.0, -7.0),
         'rotation': (0.0, 0.0, 0.0),
         'scale': 0.6}}

PLAYER_HUG = {'leftarm': (-47.7195, 29.5022, -8.4504), 'rightarm': (-46.7224, -31.3373, 6.4815)}
