# Roadmap

What's planned for Bazaar after 0.5.0. Nothing here has a date, and plans can change. Smaller fixes and ideas are in [GitHub's issues](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues).

## 0.5: out now

Bazaar 0.5.0 is the first public release. Every 0.x release after it only adds to what plugins can use, so plugins built for 0.5.0 keep working until 1.0.

## Between 0.5 and 1.0: multiplayer and hot seat, if possible

This is [#51](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/51). Until it's done, Bazaar and its plugins are single player only.

1. Play a multiplayer game and a hot seat game with Bazaar and no plugins. VMC itself was never tested in multiplayer, so if this fails in ways Bazaar can't fix, multiplayer stays out.
2. Make plugins work there: every player's computer loads the same plugins in the same order, a plugin crash on one computer doesn't put the game out of step, the crash pop-up isn't lost in hot seat when the turn passes, and the multiplayer and hot seat setup screens lead to the Plugins screen.
3. Mark Bazaar, and the templates new plugins and Lua mods start from, as working in multiplayer and hot seat.

After that: a list of plugins that players can share, which also tells them which mods they still need.

## 1.0: a clean core

Bazaar 1.0 will be the first release that breaks older plugins. It's the release where Bazaar becomes a clean base with no gameplay changes of its own. It keeps the game's own code and what mods made for VMC rely on, such as VMC's Lua events. VMC's gameplay changes and bug fixes, which are part of Bazaar today, move out into plugins: one for each of whoward69's pick'n'mix mods and one for the bug fixes. Then you choose which of them you want.

- The first step is sorting every one of VMC's changes into what stays in Bazaar and what moves.
- Bazaar 1.0 comes on new Steam Workshop items, not as an update. Games saved with 0.x need the 0.x mod, so its items stay up, and plugins built for 0.x keep working there.
- Every plugin is rebuilt for 1.0.
- Bazaar marks whoward69's original pick'n'mix mods as incompatible, and its Workshop page links to the new plugins.

## Not planned

Running Bazaar together with another mod that replaces the game DLL, such as the Community Patch or Vox Populi. Only one mod can replace it. If the Community Patch ever took up Bazaar's plugin loader, that would be their own build of it.
