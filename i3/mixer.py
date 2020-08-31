"""

This file is to be placed at ~/.config/py3status/modules/mixer.py

This module is an edited version of the volume_status py3status module found here:
https://github.com/ultrabug/py3status/blob/master/py3status/modules/volume_status.py

I claim no ownership over this code.

Volume control.

Configuration parameters:
    blocks: a string, where each character represents a volume level
            (default "_▁▂▃▄▅▆▇█")
    button_down: button to decrease volume (default 5)
    button_mute: button to toggle mute (default 1)
    button_up: button to increase volume (default 4)
    cache_timeout: how often we refresh this module in seconds.
        (default 10)
    card: Card to use. amixer supports this. (default None)
    channel: channel to track. Default value is backend dependent.
        (default None)
    command: Choose between "amixer", "pamixer" or "pactl".
        If None, try to guess based on available commands.
        (default None)
    device: Device to use. Defaults value is backend dependent.
        "aplay -L", "pactl list sinks short", "pamixer --list-sinks"
        (default None)
    format: Format of the output.
        (default '[\\?if=is_input 😮|♪]: {percentage}%')
    format_muted: Format of the output when the volume is muted.
        (default '[\\?if=is_input 😶|♪]: muted')
    is_input: Is this an input device or an output device?
        (default False)
    max_volume: Allow the volume to be increased past 100% if available.
        pactl and pamixer supports this. (default 120)
    thresholds: Threshold for percent volume.
        (default [(0, 'bad'), (20, 'degraded'), (50, 'good')])
    volume_delta: Percentage amount that the volume is increased or
        decreased by when volume buttons pressed.
        (default 5)

Format placeholders:
    {icon} Character representing the volume level,
            as defined by the 'blocks'
    {percentage} Percentage volume

Color options:
    color_muted: Volume is muted, if not supplied color_bad is used
        if set to `None` then the threshold color will be used.

Requires:
    alsa-utils: an alternative implementation of linux sound support
    pamixer: pulseaudio command-line mixer like amixer

Notes:
    If you are changing volume state by external scripts etc and
    want to refresh the module quicker than the i3status interval,
    send a USR1 signal to py3status in the keybinding.
    Example: killall -s USR1 py3status

Examples:
```
# Set thresholds to rainbow colors
volume_status {
    thresholds = [
        (0, "#FF0000"),
        (10, "#E2571E"),
        (20, "#FF7F00"),
        (30, "#FFFF00"),
        (40, "#00FF00"),
        (50, "#96BF33"),
        (60, "#0000FF"),
        (70, "#4B0082"),
        (80, "#8B00FF"),
        (90, "#FFFFFF")
    ]
}
```

@author <Jan T> <jans.tuomi@gmail.com>
@license BSD

SAMPLE OUTPUT
{'color': '#00FF00', 'full_text': u'\u266a: 95%'}

mute
{'color': '#FF0000', 'full_text': u'\u266a: muted'}
"""

import re
import math
from py3status.exceptions import CommandError

STRING_ERROR = "invalid command `%s`"
STRING_NOT_AVAILABLE = "no available binary"
COMMAND_NOT_INSTALLED = "command `%s` not installed"


class Audio:
    def __init__(self, parent):
        self.card = parent.card
        self.channel = parent.channel
        self.device = parent.device
        self.is_input = parent.is_input
        self.max_volume = parent.max_volume
        self.parent = parent
        self.setup(parent)

    def setup(self, parent):
        raise NotImplementedError

    def run_cmd(self, cmd):
        return self.parent.py3.command_run(cmd)

    def command_output(self, cmd):
        return self.parent.py3.command_output(cmd)

class Pactl(Audio):
    def setup(self, parent):
        # get available device number if not specified
        self.device_type = "source" if self.is_input else "sink"
        self.device_type_pl = self.device_type + "s"
        self.device_type_cap = self.device_type[0].upper() + self.device_type[1:]

        self.device = self.get_default_device()
        self.update_device()

    def swap_device(self, new_device):
        self.device = new_device
        self.update_device()
        self.set_default_device()
        

        for sink_input in self.get_sink_inputs():
            self.run_cmd(
                [
                    'pactl',
                    'move-sink-input',
                    sink_input,
                    str(self.device)
                ]
            )

    def update_device(self):
        self.re_volume = re.compile(
            r"{} (?:\#{}|.*?Name: {}).*?Mute: (\w{{2,3}}).*?Volume:.*?(\d{{1,3}})\%".format(
                self.device_type_cap, self.device, self.device
            ),
            re.M | re.DOTALL,
        )

    def set_default_device(self):
        self.run_cmd(
            [
                "pactl",
                "set-default-{}".format(self.device_type),
                str(self.device),
            ]
        )

    def get_device_index(self, device_id):
        if device_id is not None:
            output = self.command_output(
                ["pactl", "list", "short", self.device_type_pl]
            )
            for line in output.splitlines():
                parts = line.split()
                if len(parts) < 2:
                    continue
                if parts[1] == device_id:
                    return parts[0]

        raise RuntimeError(
            "Failed to find default {} device.  Looked for {}".format(
                "input" if self.is_input else "output", device_id
            )
        )

    def get_default_device(self, name=False):
        device_id = None

        # Find the default device for the device type
        default_dev_pattern = re.compile(
            r"^Default {}: (.*)$".format(self.device_type_cap)
        )
        output = self.command_output(["pactl", "info"])
        for info_line in output.splitlines():
            default_dev_match = default_dev_pattern.match(info_line)
            if default_dev_match is not None:
                device_id = default_dev_match.groups()[0]
                break

        if name:
            return device_id

        # with the long gross id, find the associated number
        return self.get_device_index(device_id)

    # Returns a list of integers as strings corresponding to sink inputs
    def get_sink_inputs(self):
        cmd_out = self.command_output(
            ['pactl', 'list', 'short', 'sink-inputs']
        )

        return [line.split()[0] for line in cmd_out.split("\n")[:-1]]

    def get_volume(self):
        output = self.command_output(["pactl", "list", self.device_type_pl]).strip()
        try:
            muted, perc = self.re_volume.search(output).groups()
            muted = muted == "yes"
        except AttributeError:
            muted, perc = None, None
        return perc, muted

    def volume_up(self, delta):
        perc, muted = self.get_volume()
        if int(perc) + delta >= self.max_volume:
            change = "{}%".format(self.max_volume)
        else:
            change = "+{}%".format(delta)
        self.run_cmd(
            [
                "pactl",
                "--",
                "set-{}-volume".format(self.device_type),
                self.device,
                change,
            ]
        )

    def volume_down(self, delta):
        self.run_cmd(
            [
                "pactl",
                "--",
                "set-{}-volume".format(self.device_type),
                self.device,
                "-{}%".format(delta),
            ]
        )

    def toggle_mute(self):
        self.run_cmd(
            ["pactl", "set-{}-mute".format(self.device_type), self.device, "toggle"]
        )


class Py3status:
    """
    """

    # available configuration parameters
    blocks = "_▁▂▃▄▅▆▇█"
    button_left     = 1
    button_right    = 3
    scroll_up       = 4
    scroll_down     = 5
    
    cache_timeout = 10
    card = None
    channel = None
    command = None
    device = 0
    format = r"[\?if=is_input |] {percentage}%[ - {sink_name}]"
    format_muted = r"[\?if=is_input |] {percentage}%[ - {sink_name}]"
    is_input = False
    max_volume = 200
    thresholds = [(0, "bad"), (20, "degraded"), (50, "good")]
    volume_delta = 5

    class Meta:
        def deprecate_function(config):
            # support old thresholds
            return {
                "thresholds": [
                    (0, "bad"),
                    (config.get("threshold_bad", 20), "degraded"),
                    (config.get("threshold_degraded", 50), "good"),
                ]
            }

        deprecated = {
            "function": [{"function": deprecate_function}],
            "remove": [
                {
                    "param": "threshold_bad",
                    "msg": "obsolete set using thresholds parameter",
                },
                {
                    "param": "threshold_degraded",
                    "msg": "obsolete set using thresholds parameter",
                },
            ],
        }

    def post_config_hook(self):
        if not self.command:
            commands = ["pamixer", "pactl", "amixer"]
            # pamixer, pactl requires pulseaudio to work
            if not self.py3.check_commands("pulseaudio"):
                commands = ["amixer"]
            self.command = self.py3.check_commands(commands)
        elif self.command not in ["amixer", "pamixer", "pactl"]:
            raise Exception(STRING_ERROR % self.command)
        elif not self.py3.check_commands(self.command):
            raise Exception(COMMAND_NOT_INSTALLED % self.command)
        if not self.command:
            raise Exception(STRING_NOT_AVAILABLE)

        # turn integers to strings
        if self.card is not None:
            self.card = str(self.card)
        
        self.device = 0

        self.backend = globals()[self.command.capitalize()](self)
        self.color_muted = self.py3.COLOR_MUTED or self.py3.COLOR_BAD

    def volume_status(self):

        perc, muted = self.backend.get_volume()
        color = None
        icon = None
        new_format = self.format

        if perc is None:
            perc = "?"
        elif muted:
            color = self.color_muted
            new_format = self.format_muted
        else:
            color = "#FFFFFF"
            icon = self.blocks[
                min(
                    len(self.blocks) - 1,
                    int(math.ceil(int(perc) / 100 * (len(self.blocks) - 1))),
                )
            ]
        
        volume_data = {"icon": icon, "percentage": perc}

        if self.py3.storage_get('edit_mode'):
            volume_data["sink_name"] = self.py3.storage_get('sink_name')

        return {
            "cached_until": self.py3.time_in(self.cache_timeout),
            "full_text": self.py3.safe_format(new_format, volume_data),
            "color": color,
        }

    def on_click(self, event):
        button = event["button"]

        if button == self.button_left:
            self.py3.storage_set('edit_mode', not self.py3.storage_get('edit_mode'))

            # Get default sink and store it
            self.py3.storage_set("sink_name", self.backend.get_default_device(True))

        elif button == self.button_right:
            self.backend.toggle_mute()
        
        elif self.py3.storage_get('edit_mode'):

            if button == self.scroll_up or button == self.scroll_down:
                # Grab sink index in sink list
                sink_name = self.py3.storage_get('sink_name')

                # Grab the list of sinks
                sink_list = self.__get_sink_list()

                delta = -1 if self.scroll_up else 1

                try:
                    ind = (self.__get_sink_index(sink_list, sink_name) + delta) % len(sink_list)
                except ValueError:
                    return
                
                while sink_list[ind]['state'] == 'SUSPENDED':
                    ind = (ind + delta) % len(sink_list)

                self.py3.storage_set('sink_name', sink_list[ind]['name'])
                self.backend.swap_device(ind)
    
    def __get_sink_list(self):
        cmd_out = self.py3.command_output(['pactl', 'list', 'sinks', 'short'])
        
        # grab the second element from each line
        sink_list = [
            {
                "name": line.split()[1],
                "state": line.split()[-1]
            }
            for line in cmd_out.split("\n")[:-1]
        ]

        return sink_list

    def __get_sink_index(self, sink_list, sink_name):
        for i, sink in enumerate(sink_list):
            if sink['name'] == sink_name:
                return i
        raise ValueError

if __name__ == "__main__":
    """
    Run module in test mode.
    """
    from py3status.module_test import module_test

    module_test(Py3status)
