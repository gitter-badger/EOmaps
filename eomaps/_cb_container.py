from eomaps.callbacks import (
    click_callbacks,
    pick_callbacks,
    keypress_callbacks,
    dynamic_callbacks,
)
from types import SimpleNamespace

from functools import update_wrapper, partial
from collections import defaultdict
import matplotlib.pyplot as plt

from pyproj import Transformer


class cb_container:
    """
    A container for attaching callbacks and accessing return-objects.

    - **click** : Execute functions when clicking on the map

    - **pick** : Execute functions when you "pick" a pixel on the  map
      - only available if a dataset has been plotted via `m.plot_map()`

    - **keypress** : Execute functions if you press a key on the keyboard

    - **dynamic** : Execute functions on events (e.g. zoom)

    """

    def __init__(self, m):
        self._m = m

        self.click = cb_click_container(
            m=m,
            cb_cls=click_callbacks,
            method="click",
        )
        self.pick = cb_pick_container(
            m=m,
            cb_cls=pick_callbacks,
            method="pick",
        )
        self.keypress = keypress_container(
            m=m,
            cb_cls=keypress_callbacks,
            method="keypress",
        )
        self.dynamic = dynamic_callbacks(m=m)

        self._methods = ["click", "keypress"]

    def _init_cbs(self):
        for method in self._methods:
            obj = getattr(self, method)
            obj._init_cbs()

        self._cid_onclose = self._m.figure.f.canvas.mpl_connect(
            "close_event", self._on_close
        )

        self._remove_default_keymaps()

    @staticmethod
    def _remove_default_keymaps():
        # unattach default keymaps to avoid interaction with keypress events
        assignments = dict()
        assignments["keymap.back"] = ["c", "left"]
        assignments["keymap.forward"] = ["v", "right"]
        assignments["keymap.grid"] = ["g"]
        assignments["keymap.grid_minor"] = ["G"]
        assignments["keymap.home"] = ["h", "r"]
        assignments["keymap.pan"] = ["p"]
        assignments["keymap.quit"] = ["q"]
        assignments["keymap.save"] = ["s"]
        assignments["keymap.xscale"] = ["k", "L"]
        assignments["keymap.yscale"] = ["l"]

        for key, val in assignments.items():
            for v in val:
                try:
                    plt.rcParams[key].remove(v)
                except Exception:
                    pass

    # attach a cleanup function if the figure is closed
    # to ensure callbacks are removed and the container is reinitialized
    def _on_close(self, event):
        for method in self._methods:
            obj = getattr(self, method)
            for key in obj.get.attached_callbacks:
                obj.remove(key)

        self._m._reset_axes()
        # remove all figure properties


class _cb_container(object):
    """base-class for callback containers"""

    def __init__(self, m, cb_class=None, method="click"):
        self._m = m
        self._temporary_artists = []

        self._cb = cb_class(m, self._temporary_artists)
        self._cb_list = cb_class._cb_list

        self.attach = self._attach(self)
        self.get = self._get(self)

        self._fwd_cbs = dict()

        self._method = method

    def _getobj(self, m):
        """get the equivalent callback container on anoter maps object"""
        return getattr(m.cb, self._method)

    def _clear_temporary_artists(self):
        while len(self._temporary_artists) > 0:
            art = self._temporary_artists.pop(-1)
            self._m.BM._artists_to_clear[self._method].append(art)

    def _sort_cbs(self, cbs):
        if not cbs:
            return set()
        cbnames = set([i.rsplit("_", 1)[0] for i in cbs])

        sortp = self._cb_list + list(set(self._cb_list) ^ cbnames)
        return sorted(list(cbs), key=lambda w: sortp.index(w.rsplit("_", 1)[0]))

    def __repr__(self):
        txt = "Attached callbacks:\n    " + "\n    ".join(
            f"{key}" for key in self.get.attached_callbacks
        )
        return txt

    def forward_events(self, *args):
        for m in args:
            self._fwd_cbs[id(m)] = m

    def share_events(self, *args):
        for m1 in (self._m, *args):
            for m2 in (self._m, *args):
                if m1 is not m2:
                    self._getobj(m1)._fwd_cbs[id(m2)] = m2


class _click_container(_cb_container):
    """
    A container for attaching callbacks and accessing return-objects.

    attach : accessor for callbacks.
        Executing the functions will attach the associated callback to the map!

    get : accessor for return-objects
        A container to provide easy-access to the return-values of the callbacks.

    """

    def __init__(self, m, cb_cls=None, method="pick"):
        super().__init__(m, cb_cls, method)

    class _attach:
        """
        Attach custom or pre-defined callbacks to the map.

        Each callback-function takes 2 additional keyword-arguments:

        double_click : bool
            Indicator if the callback should be executed on double-click (True)
            or on single-click events (False). The default is False
        button : int
            The mouse-button to use for executing the callback:

                - LEFT = 1
                - MIDDLE = 2
                - RIGHT = 3
                - BACK = 8
                - FORWARD = 9

            The default is 1

        For additional keyword-arguments check the doc of the callback-functions!

        Examples:
        ---------
        Get a (temporary) annotation on a LEFT-double-click:

            >>> m.cb.click.attach.annotate(double_click=True, button=1, permanent=False)
        Permanently color LEFT-clicked pixels red with a black border:

            >>> m.cb.pick.attach.mark(facecolor="r", edgecolor="k", permanent=True)
        Attach a customly defined callback

            >>> def some_callback(self, asdf, **kwargs):
            >>>     print("hello world")
            >>>     print("the position of the clicked pixel", kwargs["pos"])
            >>>     print("the data-index of the clicked pixel", kwargs["ID"])
            >>>     print("data-value of the clicked pixel", kwargs["val"])
            >>>     print("the plot-crs is:", self.plot_specs["plot_crs"])

            >>> m.cb.pick.attach(some_callback, double_click=False, button=1, asdf=1)
        """

        def __init__(self, parent):
            self._parent = parent

            # attach pre-defined callbacks
            for cb in self._parent._cb_list:
                setattr(
                    self,
                    cb,
                    update_wrapper(
                        partial(self._parent._add_callback, callback=cb),
                        getattr(self._parent._cb, cb),
                    ),
                )

        def __call__(self, f, double_click=False, button=1, **kwargs):
            """
            add a custom callback-function to the map

            Parameters
            ----------
            f : callable
                the function to attach to the map.
                The call-signature is:

                >>> def some_callback(self, **kwargs):
                >>>     print("hello world")
                >>>     print("the position of the clicked pixel", kwargs["pos"])
                >>>     print("the data-index of the clicked pixel", kwargs["ID"])
                >>>     print("data-value of the clicked pixel", kwargs["val"])
                >>>     print("the plot-crs is:", self.plot_specs["plot_crs"])
                >>>
                >>> m.cb.attach(some_callback)


            double_click : bool
                Indicator if the callback should be executed on double-click (True)
                or on single-click events (False)
            button : int
                The mouse-button to use for executing the callback:

                    - LEFT = 1
                    - MIDDLE = 2
                    - RIGHT = 3
                    - BACK = 8
                    - FORWARD = 9
            **kwargs :
                kwargs passed to the callback-function
                For documentation of the individual functions check the docs in `m.cb`


            Returns
            -------
            cid : int
                the ID of the attached callback

            """
            return self._parent._add_callback(f, double_click, button, **kwargs)

    class _get:
        def __init__(self, parent):
            self.m = parent._m
            self.cb = parent._cb

            self.cbs = defaultdict(lambda: defaultdict(dict))

        @property
        def picked_object(self):
            if hasattr(self.cb, "picked_object"):
                return self.cb.picked_object
            else:
                print("EOmaps: attach the 'load' callback first!")

        @property
        def picked_vals(self):
            if hasattr(self.cb, "picked_vals"):
                return self.cb.picked_vals
            else:
                print("EOmaps: attach the 'get_vals' callback first!")

        @property
        def permanent_markers(self):
            if hasattr(self.cb, "permanent_markers"):
                return self.cb.permanent_markers
            else:
                print("EOmaps: attach the 'mark' callback with 'permanent=True' first!")

        @property
        def permanent_annotations(self):
            if hasattr(self.cb, "permanent_annotations"):
                return self.cb.permanent_annotations
            else:
                print(
                    "EOmaps: attach the 'annotate' callback with 'permanent=True' first!"
                )

        @property
        def attached_callbacks(self):
            cbs = []
            for ds, dsdict in self.cbs.items():
                for b, bdict in dsdict.items():
                    for name in bdict.keys():
                        cbs.append(f"{name}__{ds}__{b}")

            return cbs

    def remove(self, ID=None):
        """
        remove an attached callback from the figure

        Parameters
        ----------
        callback : int, str or tuple
            if str: the name of the callback to remove
                    (`<function_name>_<count>__<double/single>__<button_ID>`)
        """
        if ID is not None:
            name, ds, b = ID.split("__")

        dsdict = self.get.cbs.get(ds, None)
        if dsdict is not None:
            bdict = dsdict.get(int(b))
        else:
            return

        if bdict is not None:
            if name in bdict:
                del bdict[name]

                # call cleanup methods on removal
                fname = name.rsplit("_", 1)[0]
                if hasattr(self._cb, f"_{fname}_cleanup"):
                    getattr(self._cb, f"_{fname}_cleanup")()

                print(f"Removed the {self._method} callback: '{ID}'.")

    def _add_callback(self, callback, double_click=False, button=1, **kwargs):
        """
        Attach a callback to the plot that will be executed if a pixel is clicked

        A list of pre-defined callbacks (accessible via `m.cb`) or customly defined
        functions can be used.

            >>> # to add a pre-defined callback use:
            >>> cid = m._add_callback("annotate", <kwargs passed to m.cb.annotate>)
            >>> # to remove the callback again, call:
            >>> m.remove_callback(cid)

        Parameters
        ----------
        callback : callable or str
            The callback-function to attach.

            If a string is provided, it will be used to assign the associated function
            from the `m.cb` collection:
                - "annotate" : add annotations to the clicked pixel
                - "mark" : add markers to the clicked pixel
                - "plot" : dynamically update a plot with the clicked values
                - "print_to_console" : print info of the clicked pixel to the console
                - "get_values" : save properties of the clicked pixel to a dict
                - "load" : use the ID of the clicked pixel to load data
                - "clear_annotations" : clear all existing annotations
                - "clear_markers" : clear all existing markers

            You can also define a custom function with the following call-signature:
                >>> def some_callback(self, asdf, **kwargs):
                >>>     print("hello world")
                >>>     print("the position of the clicked pixel", kwargs["pos"])
                >>>     print("the data-index of the clicked pixel", kwargs["ID"])
                >>>     print("data-value of the clicked pixel", kwargs["val"])
                >>>     print("the plot-crs is:", self.m.plot_specs["plot_crs"])
                >>>     print("asdf is:", asdf)

                >>> m.cb.attach(some_callback, double_click=False, button=1, asdf=1)

        double_click : bool
            Indicator if the callback should be executed on double-click (True)
            or on single-click events (False)
        button : int
            The mouse-button to use for executing the callback:

                - LEFT = 1
                - MIDDLE = 2
                - RIGHT = 3
                - BACK = 8
                - FORWARD = 9
        **kwargs :
            kwargs passed to the callback-function
            For documentation of the individual functions check the docs in `m.cb`

        Returns
        -------
        cbname : str
            the identification string of the callback
            (to remove the callback, use `m.cb.remove(cbname)`)

        """

        assert not all(
            i in kwargs for i in ["pos", "ID", "val", "double_click", "button"]
        ), 'the names "pos", "ID", "val" cannot be used as keyword-arguments!'

        if isinstance(callback, str):
            assert hasattr(self._cb, callback), (
                f"The function '{callback}' does not exist as a pre-defined callback."
                + " Use one of:\n    - "
                + "\n    - ".join(self._cb_list)
            )
            callback = getattr(self._cb, callback)
        elif callable(callback):
            # re-bind the callback methods to the eomaps.Maps.cb object
            # in case custom functions are used
            if hasattr(callback, "__func__"):
                callback = callback.__func__.__get__(self._m)
            else:
                callback = callback.__get__(self._m)

        # make sure multiple callbacks of the same funciton are only assigned
        # if multiple assignments are properly handled
        multi_cb_functions = ["mark", "annotate"]

        if double_click:
            d = self.get.cbs["double"][button]
        else:
            d = self.get.cbs["single"][button]

        # get a unique name for the callback
        ncb = [int(i.rsplit("_", 1)[1]) for i in d if i.startswith(callback.__name__)]
        cbkey = callback.__name__ + f"_{max(ncb) + 1 if len(ncb) > 0 else 0}"

        if callback.__name__ not in multi_cb_functions:
            assert len(ncb) == 0, (
                "Multiple assignments of the callback"
                + f" '{callback.__name__}' are not (yet) supported..."
            )

        d[cbkey] = partial(callback, **kwargs)

        # add mouse-button assignment as suffix to the name (with __ separator)
        cbname = cbkey + f"__{'double' if double_click else 'single'}__{button}"

        return cbname


class cb_click_container(_click_container):
    """
    Accessor to callbacks that are executed if you click anywhere on the Map.

    Methods:
    --------

    attach : accessor for callbacks.
        Executing the functions will attach the associated callback to the map!

    get : accessor for return-objects
        A container to provide easy-access to the return-values of the callbacks.

    remove : remove prviously added callbacks from the map

    forward_events : forward events to connected maps-objects

    share_events : share events between connected maps-objects (e.g. forward both ways)

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._cid_button_press_event = None
        self._cid_motion_event = None

    def _init_cbs(self):
        if self._m.parent is self._m:
            self._add_click_callback()

    def _get_clickdict(self, event):
        clickdict = dict(
            pos=(event.xdata, event.ydata),
            ID=None,
            val=None,
            ind=None,
        )

        return clickdict

    def _onclick(self, event):
        self._event = event
        clickdict = self._get_clickdict(event)

        if event.dblclick:
            cbs = self.get.cbs["double"]
        else:
            cbs = self.get.cbs["single"]

        if event.button in cbs:
            bcbs = cbs[event.button]
            for key in self._sort_cbs(bcbs):
                cb = bcbs[key]
                if clickdict is not None:
                    cb(**clickdict)

    def _add_click_callback(self):
        def clickcb(event):
            # ignore callbacks while dragging axes
            if self._m._draggable_axes._modifier_pressed:
                return
            # don't execute callbacks if a toolbar-action is active
            if (
                self._m.figure.f.canvas.toolbar is not None
            ) and self._m.figure.f.canvas.toolbar.mode != "":
                return

            # execute onclick on the parent and all its children
            # (_add_click_callback() is only called on the parent object!)
            for m in [self._m, *self._m._children]:
                if event.inaxes == m.figure.ax:
                    obj = self._getobj(m)
                    obj._onclick(event)
                    obj._fwd_cb(event)
                    m.BM._after_update_actions.append(obj._clear_temporary_artists)

            self._m.BM.update(clear=self._method)

        def movecb(event):
            # ignore callbacks while dragging axes
            if self._m._draggable_axes._modifier_pressed:
                return
            # don't execute callbacks if a toolbar-action is active
            if (
                self._m.figure.f.canvas.toolbar is not None
            ) and self._m.figure.f.canvas.toolbar.mode != "":
                return

            # only execute movecb if a mouse-button is holded down
            # and only if the motion is happening inside the axes
            if not event.button:  # or (event.inaxes != self._m.figure.ax):
                return

            for m in [self._m, *self._m._children]:
                if event.inaxes == m.figure.ax:
                    obj = self._getobj(m)
                    obj._onclick(event)
                    obj._fwd_cb(event)
                    m.BM._after_update_actions.append(obj._clear_temporary_artists)

            self._m.BM.update(clear=self._method)

        # ------------- add a callback
        self._cid_button_press_event = self._m.figure.f.canvas.mpl_connect(
            "button_press_event", clickcb
        )

        # for click-callbacks, allow motion-detection
        self._cid_motion_event = self._m.figure.f.canvas.mpl_connect(
            "motion_notify_event", movecb
        )

    def _fwd_cb(self, event):
        if event.inaxes != self._m.figure.ax:
            return

        for key, m in self._fwd_cbs.items():
            obj = self._getobj(m)

            transformer = Transformer.from_crs(
                m.crs_plot,
                self._m.crs_plot,
                always_xy=True,
            )

            # transform the coordinates of the clicked location
            xdata, ydata = transformer.transform(event.xdata, event.ydata)

            dummyevent = SimpleNamespace(
                inaxes=m.figure.ax,
                dblclick=event.dblclick,
                button=event.button,
                xdata=xdata,
                ydata=ydata,
            )
            obj._onclick(dummyevent)
            # append clear-action again since it will already be executed
            # by the first click!
            m.BM._after_update_actions.append(obj._clear_temporary_artists)


class cb_pick_container(_click_container):
    """
    Accessor to callbacks that are executed if you click on (or close-to)
    a data-point of a previously plotted collection (you must plot a dataset first!)

    The event will search for the closest data-point and execute the callback
    with the properties (e.g. position , ID, value) of the selected point.

    Methods:
    --------

    attach : accessor for callbacks.
        Executing the functions will attach the associated callback to the map!

    get : accessor for return-objects
        A container to provide easy-access to the return-values of the callbacks.

    remove : remove prviously added callbacks from the map

    forward_events : forward events to connected maps-objects

    share_events : share events between connected maps-objects (e.g. forward both ways)

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cid_pick_event = None

    def _init_cbs(self):
        if self._m.parent is self._m:
            if getattr(self._m.figure, "coll", None) is not None:
                self._add_pick_callback()

    def _get_pickdict(self, event):
        ind = event.ind
        if ind is not None:
            if event.artist is self._m.figure.coll:
                clickdict = dict(
                    pos=(self._m._props["x0"][ind], self._m._props["y0"][ind]),
                    ID=self._m._props["ids"][ind],
                    val=self._m._props["z_data"][ind],
                    ind=ind,
                )

                return clickdict

    def _onpick(self, event):
        # don't execute callbacks if a toolbar-action is active
        if (
            self._m.figure.f.canvas.toolbar is not None
        ) and self._m.figure.f.canvas.toolbar.mode != "":
            return

        self._event = event
        if event.artist != self._m.figure.coll:
            return
        else:
            clickdict = self._get_pickdict(event)

        clickdict = self._get_pickdict(event)

        if event.dblclick:
            cbs = self.get.cbs["double"]
        else:
            cbs = self.get.cbs["single"]

        if event.button in cbs:
            bcbs = cbs[event.button]
            for key in self._sort_cbs(bcbs):
                cb = bcbs[key]
                if clickdict is not None:
                    cb(**clickdict)

            self._m.BM.update(clear=self._method, blit=False)

    def _add_pick_callback(self):
        # only attach pick-callbacks if there is a collection available!
        if self._m.figure.coll is None:
            return
        # ------------- add a callback
        # execute onpick on the parent and all its children
        # (_add_pick_callback() is only called on the parent object!)
        def pickcb(event):
            # ignore callbacks while dragging axes
            if self._m._draggable_axes._modifier_pressed:
                return
            # don't execute callbacks if a toolbar-action is active
            if (
                self._m.figure.f.canvas.toolbar is not None
            ) and self._m.figure.f.canvas.toolbar.mode != "":
                return

            # execute onclick on the parent and all its children
            for m in [self._m, *self._m._children]:
                obj = self._getobj(m)
                obj._onpick(event)
                obj._fwd_cb(event)
                self._m.BM._after_update_actions.append(obj._clear_temporary_artists)
            # don't update since updates are performed within the click-callbacks
            # self._m.BM.update()

        # ------------- add a callback
        self._cid_pick_event = self._m.figure.f.canvas.mpl_connect("pick_event", pickcb)

    def _fwd_cb(self, event):
        if event.mouseevent.inaxes != self._m.figure.ax:
            return

        for key, m in self._fwd_cbs.items():
            obj = self._getobj(m)

            # TODO do we need correct xdata & ydata coords in here?
            # # transform the coordinates of the clicked location
            # xdata, ydata = m.crs_plot.transform_point(event.xdata,
            #                                           event.ydata,
            #                                           self._m.crs_plot)

            dummyevent = SimpleNamespace(
                artist=m.figure.coll,
                dblclick=event.dblclick,
                button=event.button,
            )
            dummymouseevent = SimpleNamespace(
                inaxes=m.figure.ax,
                dblclick=event.dblclick,
                button=event.button,
                xdata=event.mouseevent.xdata,
                ydata=event.mouseevent.ydata,
                x=event.mouseevent.x,
                y=event.mouseevent.y,
            )

            pick = m._pick_pixel(None, dummymouseevent)
            if pick[1] is not None:
                dummyevent.ind = pick[1]["ind"]
                if "dist" in pick[1]:
                    dummyevent.dist = pick[1]["dist"]
            else:
                dummyevent.ind = None
                dummyevent.dist = None

            obj._onpick(dummyevent)


class keypress_container(_cb_container):
    """
    Accessor to callbacks that are executed on keypress-events

    Methods:

    attach : accessor for callbacks.
        Executing the functions will attach the associated callback to the map!

    get : accessor for return-objects
        A container to provide easy-access to the return-values of the callbacks.

    remove : remove prviously added callbacks from the map

    forward_events : forward events to connected maps-objects

    share_events : share events between connected maps-objects (e.g. forward both ways)

    """

    def __init__(self, m, cb_cls=None, method="pick"):
        super().__init__(m, cb_cls, method)

    def _init_cbs(self):
        if self._m.parent is self._m:
            self._initialize_callbacks()

    def _initialize_callbacks(self):
        def _onpress(event):
            self._event = event

            if event.key in self.get.cbs:
                for name, cb in self.get.cbs[event.key].items():
                    cb(key=event.key)

        self._cid_keypress_event = self._m.figure.f.canvas.mpl_connect(
            "key_press_event", _onpress
        )

    class _attach:
        """
        Attach custom or pre-defined callbacks on keypress events.

        Each callback takes 1 additional keyword-arguments:

        key : str
            the key to use
            (modifiers are attached with a '+', e.g. "alt+d" )

        For additional keyword-arguments check the doc of the callback-functions!

        Examples
        --------

            >>> m.cb.keypress.attach.switch_layer(layer=1, key="1")

        """

        def __init__(self, parent):
            self._parent = parent

            # attach pre-defined callbacks
            for cb in self._parent._cb_list:
                setattr(
                    self,
                    cb,
                    update_wrapper(
                        partial(self._parent._add_callback, callback=cb),
                        getattr(self._parent._cb, cb),
                    ),
                )

        def __call__(self, f, key, **kwargs):
            """
            add a custom callback-function to the map

            Parameters
            ----------
            f : callable
                the function to attach to the map.
                The call-signature is:

                >>> def some_callback(self, **kwargs):
                >>>     print("hello world")
                >>>
                >>> m.cb.attach(some_callback)

            key : str
                the key to use
                (modifiers are attached with a '+', e.g. "alt+d" )

            **kwargs :
                kwargs passed to the callback-function
                For documentation of the individual functions check the docs in `m.cb`

            Returns
            -------
            cid : int
                the ID of the attached callback

            """
            return self._parent._add_callback(f, key, **kwargs)

    class _get:
        def __init__(self, parent):
            self.m = parent._m
            self.cb = parent._cb

            self.cbs = defaultdict(dict)

        @property
        def attached_callbacks(self):
            cbs = []
            for key, cbdict in self.cbs.items():
                for name, cb in cbdict.items():
                    cbs.append(f"{name}__{key}")

            return cbs

    def remove(self, ID=None):
        """
        remove an attached callback from the figure

        Parameters
        ----------
        callback : int, str or tuple
            if str: the name of the callback to remove
                    (`<function_name>_<count>__<key>`)
        """
        if ID is not None:
            name, key = ID.split("__")

        cbs = self.get.cbs.get(key, None)

        if cbs is not None:
            if name in cbs:
                del cbs[name]

                # call cleanup methods on removal
                fname = name.rsplit("_", 1)[0]
                if hasattr(self._cb, f"_{fname}_cleanup"):
                    getattr(self._cb, f"_{fname}_cleanup")()

                print(f"Removed the {self._method} callback: '{ID}'.")

    def _add_callback(self, callback, key="x", **kwargs):
        """
        Attach a callback to the plot that will be executed if a key is pressed

        A list of pre-defined callbacks (accessible via `m.cb`) or customly defined
        functions can be used.

            >>> # to add a pre-defined callback use:
            >>> cid = m._add_callback("annotate", <kwargs passed to m.cb.annotate>)
            >>> # to remove the callback again, call:
            >>> m.remove_callback(cid)

        Parameters
        ----------
        callback : callable or str
            The callback-function to attach.

        key : str
            the key to use
            (modifiers are attached with a '+', e.g. "alt+d" )

        **kwargs :
            kwargs passed to the callback-function
            For documentation of the individual functions check the docs in `m.cb`

        Returns
        -------
        cbname : str
            the identification string of the callback
            (to remove the callback, use `m.cb.remove(cbname)`)

        """

        if isinstance(callback, str):
            assert hasattr(self._cb, callback), (
                f"The function '{callback}' does not exist as a pre-defined callback."
                + " Use one of:\n    - "
                + "\n    - ".join(self._cb_list)
            )
            callback = getattr(self._cb, callback)
        elif callable(callback):
            # re-bind the callback methods to the eomaps.Maps.cb object
            # in case custom functions are used
            if hasattr(callback, "__func__"):
                callback = callback.__func__.__get__(self._m)
            else:
                callback = callback.__get__(self._m)

        cbdict = self.get.cbs[key]
        # get a unique name for the callback
        ncb = [
            int(i.rsplit("_", 1)[1]) for i in cbdict if i.startswith(callback.__name__)
        ]
        cbkey = callback.__name__ + f"_{max(ncb) + 1 if len(ncb) > 0 else 0}"

        # append the callback
        cbdict[cbkey] = partial(callback, **kwargs)

        return cbkey + f"__{key}"
