#include <furi.h>
#include <gui/gui.h>
#include <gui/modules/widget.h>
#include <input/input.h>

typedef struct {
    Widget* widget;
    FuriMessageQueue* input_queue;
} ExampleContext;

static void example_input_callback(InputEvent* input_event, void* ctx) {
    furi_assert(ctx);
    FuriMessageQueue* input_queue = ctx;
    furi_message_queue_put(input_queue, input_event, FuriWaitForever);
}

int32_t example_hello_world_main(void* p) {
    UNUSED(p);

    ExampleContext context = {0};
    context.input_queue = furi_message_queue_alloc(8, sizeof(InputEvent));
    context.widget = widget_alloc();
    widget_add_string_element(
        context.widget, 64, 16, AlignCenter, AlignTop, FontPrimary, "Hello World");
    widget_add_string_element(
        context.widget, 64, 32, AlignCenter, AlignTop, FontSecondary, "Zero_SIM example app");
    widget_add_string_element(
        context.widget, 64, 52, AlignCenter, AlignTop, FontSecondary, "Press Back to exit");

    ViewPort* view_port = widget_get_view(context.widget);
    view_port_input_callback_set(view_port, example_input_callback, context.input_queue);

    Gui* gui = furi_record_open(RECORD_GUI);
    gui_add_view_port(gui, view_port, GuiLayerFullscreen);

    InputEvent event;
    bool running = true;
    while(running) {
        if(furi_message_queue_get(context.input_queue, &event, FuriWaitForever) == FuriStatusOk) {
            if(event.type == InputTypeShort && event.key == InputKeyBack) {
                running = false;
            }
        }
    }

    gui_remove_view_port(gui, view_port);
    furi_record_close(RECORD_GUI);
    widget_free(context.widget);
    furi_message_queue_free(context.input_queue);

    return 0;
}
