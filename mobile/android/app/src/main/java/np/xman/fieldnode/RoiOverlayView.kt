package np.xman.fieldnode

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View

/**
 * Transparent layer over the camera preview: drag to draw the monitoring rectangle. Coordinates are
 * fractions of the displayed camera image ([contentAspect] = width / height, the preview is FIT_CENTER so
 * the whole frame is visible), i.e. upright NormRect coordinates. Locked while monitoring.
 */
class RoiOverlayView @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {
    var contentAspect = 3f / 4f  // 4:3 sensor frame shown in portrait
        set(value) { field = value; invalidate() }
    var roi: NormRect = NormRect.FULL
        set(value) { field = value; invalidate() }
    var locked = false
        set(value) { field = value; invalidate() }
    var onRoiSelected: ((NormRect) -> Unit)? = null
    var onRoiRejected: (() -> Unit)? = null

    private var dragStart: Pair<Float, Float>? = null
    private var dragNow: Pair<Float, Float>? = null
    private val dim = Paint().apply { color = Color.argb(110, 0, 0, 0) }
    private val stroke = Paint().apply { style = Paint.Style.STROKE; strokeWidth = 6f; color = Color.rgb(255, 193, 7) }
    private val text = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; textSize = 40f; setShadowLayer(4f, 0f, 0f, Color.BLACK) }
    private val contentRect = RectF()  // reused: no allocation while drawing
    private val areaRect = RectF()

    /** Where the camera image is drawn inside this view (FIT_CENTER). */
    private fun content(): RectF {
        val w = width.toFloat()
        val h = height.toFloat()
        if (w / h > contentAspect) {
            val cw = h * contentAspect
            contentRect.set((w - cw) / 2, 0f, (w + cw) / 2, h)
        } else {
            val ch = w / contentAspect
            contentRect.set(0f, (h - ch) / 2, w, (h + ch) / 2)
        }
        return contentRect
    }

    private fun toNorm(x: Float, y: Float): Pair<Float, Float> {
        val c = content()
        return ((x - c.left) / c.width()) to ((y - c.top) / c.height())
    }

    override fun onDraw(canvas: Canvas) {
        val c = content()
        val a = dragStart
        val b = dragNow
        val r = areaRect
        if (a != null && b != null) r.set(minOf(a.first, b.first), minOf(a.second, b.second),
                                          maxOf(a.first, b.first), maxOf(a.second, b.second))
        else r.set(c.left + roi.left * c.width(), c.top + roi.top * c.height(),
                   c.left + roi.right * c.width(), c.top + roi.bottom * c.height())
        if (!roi.isFull || a != null) {
            canvas.drawRect(c.left, c.top, c.right, r.top, dim)
            canvas.drawRect(c.left, r.bottom, c.right, c.bottom, dim)
            canvas.drawRect(c.left, r.top, r.left, r.bottom, dim)
            canvas.drawRect(r.right, r.top, c.right, r.bottom, dim)
            canvas.drawRect(r, stroke)
            canvas.drawText(if (locked) "Monitoring selected area" else "Selected area", r.left + 12, r.top + 48, text)
        } else if (!locked) {
            canvas.drawText("Drag to select the area to monitor", c.left + 24, c.top + 64, text)
        }
    }

    @SuppressLint("ClickableViewAccessibility")  // drawing gesture; the same choice is available via "Use full frame"
    override fun onTouchEvent(e: MotionEvent): Boolean {
        if (locked) return false
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> { dragStart = e.x to e.y; dragNow = dragStart }
            MotionEvent.ACTION_MOVE -> dragNow = e.x to e.y
            MotionEvent.ACTION_UP -> {
                val s = dragStart
                if (s != null) {
                    val (x1, y1) = toNorm(s.first, s.second)
                    val (x2, y2) = toNorm(e.x, e.y)
                    val selected = NormRect.of(x1, y1, x2, y2)
                    if (selected != null) { roi = selected; onRoiSelected?.invoke(selected) } else onRoiRejected?.invoke()
                }
                dragStart = null; dragNow = null
            }
            MotionEvent.ACTION_CANCEL -> { dragStart = null; dragNow = null }
        }
        invalidate()
        return true
    }
}
