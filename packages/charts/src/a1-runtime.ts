import { Cartesian, Transpose } from '@antv/g2/esm/coordinate/index';
import { Constant, Field, Transform, Column } from '@antv/g2/esm/encode/index';
import { Interval, Area, Line, Point, Cell } from '@antv/g2/esm/mark/index';
import { Category10, Category20 } from '@antv/g2/esm/palette/index';
import { Linear as ScaleLinear, Ordinal as ScaleOrdinal, Band as ScaleBand, Identity as ScaleIdenity, Point as ScalePoint, Time as ScaleTime, Log as ScaleLog, Pow as ScalePow, Threshold as ScaleThreshold, Quantile as ScaleQuantile, Quantize as ScaleQuantize, Sqrt as ScaleSqrt, Sequential as ScaleSequential, Constant as ScaleConstant, } from '@antv/g2/esm/scale/index';
import { Classic, Light } from '@antv/g2/esm/theme/index';
import { AxisLinear, AxisArc, AxisX, AxisY, AxisRadar, LegendCategory, LegendContinuous, LegendContinuousBlock, LegendContinuousBlockSize, LegendContinuousSize, TitleComponent, SliderX, SliderY, ScrollbarX, ScrollbarY, Legends, } from '@antv/g2/esm/component/index';
import { ScaleInX, ScaleOutX, ScaleInY, ScaleOutY, WaveIn, FadeIn, FadeOut, Morphing, } from '@antv/g2/esm/animation/index';
import { Tooltip, LegendFilter, LegendHighlight, SliderFilter, Poptip, Event, ScrollbarFilter, } from '@antv/g2/esm/interaction/index';
import { Mark, View } from '@antv/g2/esm/composition/index';
import { LabelShape } from '@antv/g2/esm/shape/index';
import { Inline } from '@antv/g2/esm/data/index';


export const library = {
        'data.inline': Inline,
        'coordinate.cartesian': Cartesian,
        'coordinate.transpose': Transpose,
        'encode.constant': Constant,
        'encode.field': Field,
        'encode.transform': Transform,
        'encode.column': Column,
        'mark.interval': Interval,
        'mark.area': Area,
        'mark.line': Line,
        'mark.point': Point,
        'mark.cell': Cell,
        'shape.label.label': LabelShape,
        'palette.category10': Category10,
        'palette.category20': Category20,
        'scale.linear': ScaleLinear,
        'scale.ordinal': ScaleOrdinal,
        'scale.band': ScaleBand,
        'scale.identity': ScaleIdenity,
        'scale.point': ScalePoint,
        'scale.time': ScaleTime,
        'scale.log': ScaleLog,
        'scale.pow': ScalePow,
        'scale.sqrt': ScaleSqrt,
        'scale.threshold': ScaleThreshold,
        'scale.quantile': ScaleQuantile,
        'scale.quantize': ScaleQuantize,
        'scale.sequential': ScaleSequential,
        'scale.constant': ScaleConstant,
        // G2 5.4.8 defaults a chart's theme `type` to 'light'
        // (esm/runtime/plot.js inferTheme), and useLibrary('theme', lib) then
        // resolves 'theme.light'. Registering only 'theme.classic' made every
        // probe sample throw `Unknown Component: theme.light` in the browser.
        'theme.light': Light,
        'theme.classic': Classic,
        'component.axisX': AxisX,
        'component.axisY': AxisY,
        'component.axisRadar': AxisRadar,
        'component.axisLinear': AxisLinear,
        'component.axisArc': AxisArc,
        'component.legendCategory': LegendCategory,
        'component.legendContinuous': LegendContinuous,
        'component.legendContinuousBlock': LegendContinuousBlock,
        'component.legendContinuousBlockSize': LegendContinuousBlockSize,
        'component.legendContinuousSize': LegendContinuousSize,
        'component.legends': Legends,
        'component.title': TitleComponent,
        'component.sliderX': SliderX,
        'component.sliderY': SliderY,
        'component.scrollbarX': ScrollbarX,
        'component.scrollbarY': ScrollbarY,
        'animation.scaleInX': ScaleInX,
        'animation.scaleOutX': ScaleOutX,
        'animation.scaleInY': ScaleInY,
        'animation.scaleOutY': ScaleOutY,
        'animation.waveIn': WaveIn,
        'animation.fadeIn': FadeIn,
        'animation.fadeOut': FadeOut,
        'animation.morphing': Morphing,
        'interaction.tooltip': Tooltip,
        'interaction.legendFilter': LegendFilter,
        'interaction.legendHighlight': LegendHighlight,
        'interaction.sliderFilter': SliderFilter,
        'interaction.scrollbarFilter': ScrollbarFilter,
        'interaction.poptip': Poptip,
        'interaction.event': Event,
        'composition.mark': Mark,
        'composition.view': View,
};
